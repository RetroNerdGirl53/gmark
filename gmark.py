#!/usr/bin/env python3


import sys
import os
import argparse
import re
import urllib.request
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
        description="Parse radio frequency data from a file, URL or stdin and format it for GQRX bookmarks.",
        epilog="Examples:\n"
               "  gmark.py --input-file freqs.txt bookmarks.csv\n"
               "  gmark.py --url http://example.com/freqs bookmarks.csv\n"
               "  cat freqs.txt | gmark.py bookmarks.csv"
    )
    parser.add_argument("output_file", help="Output CSV file for GQRX bookmarks.")
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--input-file", help="Input text file containing radio frequency data.")
    input_group.add_argument("--url", help="URL to fetch frequency data from.")

    parser.add_argument(
        "--new",
        action="store_true",
        help="Overwrite the output file if it exists. By default, new entries are appended."
    )
    args = parser.parse_args()

    if args.url:
        html_content = get_web_content(args.url)
        if html_content:
            rows, tags = parse_web_data(html_content)
            if not rows:
                print("Could not find any frequencies in the URL.", file=sys.stderr)
                sys.exit(1)
            write_bookmarks(args.output_file, rows, tags, overwrite=args.new)
        else:
            sys.exit(1)
    elif args.input_file:
        with open(args.input_file, "r") as f:
            input_data = f.readlines()
        rows, tags = parse_data(input_data)
        write_bookmarks(args.output_file, rows, tags, overwrite=args.new)
    elif not sys.stdin.isatty():
        input_data = sys.stdin.readlines()
        rows, tags = parse_data(input_data)
        write_bookmarks(args.output_file, rows, tags, overwrite=args.new)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
