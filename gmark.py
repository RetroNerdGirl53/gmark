#!/usr/bin/env python3


import sys
import os
import argparse
import re
import urllib.request
import json
from bs4 import BeautifulSoup

def convert_frequency(freq, unit="mhz"):
    if unit == "hz":
        return int(freq * 1_000_000)  # MHz to Hz
    elif unit == "khz":
        return int(freq * 1_000)  # MHz to kHz
    elif unit == "ghz":
        return freq / 1_000  # MHz to GHz
    return freq  # Default to MHz

def parse_data(input_data):
    rows = []
    tags = set()
    for line in input_data:
        columns = line.split('\t')
        if len(columns) < 8:
            continue  # Skip malformed lines

        try:
            freq = float(columns[0])  # Frequency in MHz
            converted_freq = convert_frequency(freq, unit="hz")
            name = columns[4].strip()
            if not name:
                continue  # Skip entries without a name
            mode = columns[6].strip()
            mode = "Narrow FM" if mode == "FMN" else mode
            bandwidth = ""  # Default to empty
            if mode == "Narrow FM" or mode.startswith("AM"):
                bandwidth = "10000"
            elif mode in {"LSB", "USB"}:
                bandwidth = "2700"
            tags_field = columns[7].strip().replace(" ", "")  # Remove spaces around commas

            row = f"{converted_freq}; {name}             ; {mode}                  ;      {bandwidth}; {tags_field}"
            rows.append(row)

            if tags_field:
                tags.update(tags_field.split(","))
        except ValueError:
            continue  # Skip rows with invalid data

    return rows, tags

def write_bookmarks(output_file, rows, tags, overwrite=False):
    if overwrite or not os.path.exists(output_file):
        with open(output_file, "w") as f:
            for tag in sorted(list(tags)):
                f.write(f"{tag} ; #c0c0c0\n")
            f.write("\n")  # Add an empty line between tags and data

    with open(output_file, "a") as f:
        for row in rows:
            f.write(row + "\n")

def get_web_content(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            return response.read()
    except Exception as e:
        print(f"Error fetching URL {url}: {e}", file=sys.stderr)
        return None

# --- AI Service Framework ---

class AIService:
    def __init__(self, args):
        self.args = args

    def list_models(self):
        raise NotImplementedError

    def generate_tags(self, frequency_data):
        raise NotImplementedError

class OllamaService(AIService):
    def _get_ollama_url(self, endpoint):
        return f"http://{self.args.ollama_host}:{self.args.ollama_port}{endpoint}"

    def list_models(self):
        try:
            url = self._get_ollama_url('/api/tags')
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())
                return [model['name'] for model in data.get('models', [])]
        except Exception as e:
            print(f"Error connecting to Ollama at {self.args.ollama_host}:{self.args.ollama_port}. Is Ollama running?", file=sys.stderr)
            print(f"Details: {e}", file=sys.stderr)
            return None

    def generate_tags(self, rows):
        print(f"Generating tags with Ollama using model: {self.args.ollama_model}...")

        # Prepare the data for the prompt
        freq_list_str = ""
        for i, row in enumerate(rows):
            # The row is a semicolon-delimited string. We need the frequency and description.
            parts = row.split(';')
            freq_hz = parts[0].strip()
            desc = parts[1].strip()
            freq_mhz = int(freq_hz) / 1_000_000
            freq_list_str += f"{i}: {freq_mhz:.3f} MHz - {desc}\n"

        prompt = (
            "You are an expert in radio communications. Your task is to analyze a list of radio frequencies and their descriptions. "
            "For each entry, provide a comma-separated list of 3-5 relevant, single-word, lowercase tags. "
            "Focus on tags that describe the service type (e.g., 'ham', 'business', 'aviation', 'marine', 'public-safety'), "
            "the modulation (e.g., 'fm', 'ssb', 'dmr', 'p25'), or the purpose (e.g., 'repeater', 'simplex', 'satellite', 'emergency').\n\n"
            "Here is the list of frequencies:\n"
            f"{freq_list_str}\n"
            "Provide your response as a single JSON object, where each key is the entry's index number (as a string) and the value is the comma-separated string of tags. "
            "Example: {\"0\": \"ham,repeater,vhf,fm\", \"1\": \"aviation,am,air-traffic-control\"}"
        )

        request_data = {
            "model": self.args.ollama_model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }

        try:
            url = self._get_ollama_url('/api/generate')
            req = urllib.request.Request(url, data=json.dumps(request_data).encode('utf-8'), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as response:
                body = response.read().decode()
                response_data = json.loads(body)
                ai_tags_str = response_data.get('response', '{}')
                ai_tags = json.loads(ai_tags_str)
        except Exception as e:
            print(f"Error during Ollama API call: {e}", file=sys.stderr)
            return rows, set()

        # Integrate the AI tags back into the rows
        new_rows = []
        all_tags = set()
        for i, row in enumerate(rows):
            parts = row.split(';')
            tags_from_ai = ai_tags.get(str(i), '')
            parts[4] = f" {tags_from_ai.replace(',', ' ')}" # Add space for alignment
            new_row = ";".join(parts)
            new_rows.append(new_row)

            if tags_from_ai:
                all_tags.update(tags_from_ai.split(','))

        return new_rows, all_tags

def get_ai_service(args):
    provider = args.ai_provider.lower()
    if provider == 'ollama':
        return OllamaService(args)
    # Add other providers here as they are implemented
    # elif provider == 'openai':
    #     return OpenAIService(args)
    else:
        print(f"Error: AI provider '{provider}' is not supported.", file=sys.stderr)
        sys.exit(1)


def parse_web_data(html_content):
    soup = BeautifulSoup(html_content, 'lxml')
    rows = []
    tags = set()
    processed_rows = set()

    freq_regex = re.compile(r'\b(\d{1,3}(?:,?\d{3})*(?:\.\d+)?)\s*(MHz|kHz|GHz)?\b', re.IGNORECASE)

    for table in soup.find_all('table'):
        for tr in table.find_all('tr'):
            cells = tr.find_all(['td', 'th'])
            if not cells: continue

            freq_cell_index = -1
            freq_match = None
            for i, cell in enumerate(cells):
                text = cell.get_text().replace(',', '')
                match = freq_regex.search(text)
                if match:
                    freq_cell_index = i
                    freq_match = match
                    break

            if freq_cell_index != -1:
                desc_parts = [cell.get_text(strip=True) for i, cell in enumerate(cells) if i != freq_cell_index]
                name = ' '.join(filter(None, desc_parts))
                name = ' '.join(name.split())
                name = name.encode('ascii', 'ignore').decode('ascii')
                if not name: continue

                freq_str, unit_str = freq_match.groups()
                freq_str = freq_str.replace(',', '')
                unit = unit_str.lower() if unit_str else 'mhz'

                try:
                    freq = float(freq_str)
                    if unit == 'ghz': freq_mhz = freq * 1000
                    elif unit == 'khz': freq_mhz = freq / 1000
                    else: freq_mhz = freq

                    if not (0.1 <= freq_mhz <= 30000): continue

                    converted_freq = convert_frequency(freq_mhz, unit="hz")

                    lower_text = name.lower()
                    if re.search(r'\blsb\b', lower_text): mode = 'LSB'; bandwidth = '2700'
                    elif re.search(r'\busb\b', lower_text): mode = 'USB'; bandwidth = '2700'
                    elif re.search(r'\bnfm\b', lower_text) or re.search(r'\bnarrow\b', lower_text): mode = 'Narrow FM'; bandwidth = '10000'
                    elif re.search(r'\bfm\b', lower_text): mode = 'FM'; bandwidth = '12500'
                    elif re.search(r'\bam\b', lower_text): mode = 'AM'; bandwidth = '10000'
                    elif re.search(r'\bcw\b', lower_text): mode = 'CW'; bandwidth = '500'
                    elif re.search(r'\bdigital\b', lower_text) or re.search(r'\bd-star\b', lower_text): mode = 'digital'; bandwidth = '6250'
                    else: mode = "FM"; bandwidth = "12500"

                    tags_field = ""
                    row = f"{converted_freq}; {name}             ; {mode}                  ;      {bandwidth}; {tags_field}"
                    if row not in processed_rows:
                        rows.append(row)
                        processed_rows.add(row)

                except (ValueError, IndexError):
                    continue

    if not rows:
        for element in soup.find_all(['p', 'li']):
            text = element.get_text(separator=' ', strip=True).replace(',', '')
            if len(text) > 200: continue

            match = freq_regex.search(text)
            if match:
                freq_str, unit_str = match.groups()
                freq_str = freq_str.replace(',', '')
                unit = unit_str.lower() if unit_str else 'mhz'
                try:
                    freq = float(freq_str)
                    if unit == 'ghz': freq_mhz = freq * 1000
                    elif unit == 'khz': freq_mhz = freq / 1000
                    else: freq_mhz = freq
                    if not (0.1 <= freq_mhz <= 30000): continue
                    converted_freq = convert_frequency(freq_mhz, unit="hz")

                    name = text.replace(match.group(0), '').strip()
                    name = ' '.join(name.split())
                    name = name.encode('ascii', 'ignore').decode('ascii')
                    if not name: continue

                    lower_text = name.lower()
                    if re.search(r'\blsb\b', lower_text): mode = 'LSB'; bandwidth = '2700'
                    elif re.search(r'\busb\b', lower_text): mode = 'USB'; bandwidth = '2700'
                    elif re.search(r'\bnfm\b', lower_text) or re.search(r'\bnarrow\b', lower_text): mode = 'Narrow FM'; bandwidth = '10000'
                    elif re.search(r'\bfm\b', lower_text): mode = 'FM'; bandwidth = '12500'
                    elif re.search(r'\bam\b', lower_text): mode = 'AM'; bandwidth = '10000'
                    elif re.search(r'\bcw\b', lower_text): mode = 'CW'; bandwidth = '500'
                    elif re.search(r'\bdigital\b', lower_text) or re.search(r'\bd-star\b', lower_text): mode = 'digital'; bandwidth = '6250'
                    else: mode = "FM"; bandwidth = "12500"

                    tags_field = ""
                    row = f"{converted_freq}; {name}             ; {mode}                  ;      {bandwidth}; {tags_field}"
                    if row not in processed_rows:
                        rows.append(row)
                        processed_rows.add(row)
                except (ValueError, IndexError):
                    continue

    return rows, tags

def main():
    parser = argparse.ArgumentParser(
        description="A powerful tool to generate GQRX bookmark files from websites, local files, or text input. "
                    "It intelligently parses frequency data and can use AI language models to automatically "
                    "categorize and tag the frequencies.",
        epilog="""
Usage Examples:

  # Basic URL parsing (with AI tagging by default)
  gmark.py --url https://www.radioreference.com/db/browse/coid/1 bookmarks.csv

  # Parsing from a local file without AI tagging
  gmark.py --input-file my_freqs.txt --no-ai bookmarks.csv

  # Piping text from another command
  cat my_freqs.txt | gmark.py bookmarks.csv

  # Using a specific Ollama model for tagging
  gmark.py --url <URL> --ollama-model "llama2:13b" bookmarks.csv

  # Listing available models from your Ollama server
  gmark.py --list-ollama-models

  # Using a different AI provider (once implemented)
  # gmark.py --url <URL> --ai-provider openai --api-key "sk-..." bookmarks.csv
""",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("output_file", nargs='?', default=None, help="Output CSV file for GQRX bookmarks. Required unless listing models.")
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--input-file", help="Input text file containing radio frequency data.")
    input_group.add_argument("--url", help="URL to fetch frequency data from.")

    parser.add_argument(
        "--new",
        action="store_true",
        help="Overwrite the output file if it exists. By default, new entries are appended."
    )

    ai_group = parser.add_argument_group('AI Options for Tagging and Categorization')
    ai_group.add_argument('--no-ai', action='store_true', help='Disable AI-powered categorization and tagging. Default is to use AI.')
    ai_group.add_argument('--ai-provider', type=str, default='ollama', choices=['ollama', 'openai', 'anthropic', 'gemini', 'venice', 'deepseek'], help='The AI provider to use for processing frequencies. Default is "ollama".')
    ai_group.add_argument('--api-key', type=str, help='API key for the selected cloud-based AI provider.')
    ai_group.add_argument('--ollama-host', type=str, default='127.0.0.1', help='The hostname or IP address of the Ollama API server. Default is "127.0.0.1".')
    ai_group.add_argument('--ollama-port', type=int, default=11434, help='The port number for the Ollama API server. Default is 11434.')
    ai_group.add_argument('--ollama-model', type=str, default='llama3', help='The name of the Ollama model to use for processing. Default is "llama3".')
    ai_group.add_argument('--list-ollama-models', action='store_true', help='List available models from the Ollama server and exit.')

    args = parser.parse_args()

    ai_service = None
    if not args.no_ai:
        ai_service = get_ai_service(args)

    if args.list_ollama_models:
        if args.ai_provider == 'ollama':
            models = ai_service.list_models()
            if models is not None:
                print("Available Ollama Models:")
                for model in models:
                    print(f"- {model}")
            # The list_models function already prints errors
        else:
            print("Model listing is only supported for the 'ollama' provider.")
        sys.exit(0)

    if not args.output_file:
        parser.error("the following arguments are required: output_file")

    rows, tags = [], set()

    if args.url:
        html_content = get_web_content(args.url)
        if html_content:
            rows, tags = parse_web_data(html_content)
    elif args.input_file:
        with open(args.input_file, "r") as f:
            rows, tags = parse_data(f.readlines())
    elif not sys.stdin.isatty():
        rows, tags = parse_data(sys.stdin.readlines())
    else:
        parser.print_help()
        sys.exit(1)

    if not rows:
        print("No frequency data found from the specified input.", file=sys.stderr)
        sys.exit(1)

    if ai_service:
        rows, tags = ai_service.generate_tags(rows)

    write_bookmarks(args.output_file, rows, tags, overwrite=args.new)

if __name__ == "__main__":
    main()
