"""Convert a user-downloaded NLR/ESIF zipped CSV to one auditable month.

Download the *Power Metrics Timeseries Data (Zipped CSV)* from
https://data.nlr.gov/submissions/300. No private or invented raw data included.

Usage:
 python -m scripts.prepare_esif /path/to/esif.csv.zip data/esif_month.csv
"""
import argparse
from pathlib import Path
from zipfile import ZipFile
import pandas as pd
from pcm.workload import normalize_month


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Official zip or CSV source")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.source.suffix.lower() == ".zip":
        with ZipFile(args.source) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise ValueError("ZIP contains no CSV files")
            with z.open(sorted(names)[0]) as stream:
                raw = pd.read_csv(stream)
    else:
        raw = pd.read_csv(args.source)
    month = normalize_month(raw)
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    month.to_csv(args.destination, index=False)
    print(f"Saved {len(month)} hourly samples: {month.timestamp.iloc[0]} through {month.timestamp.iloc[-1]}")


if __name__ == "__main__":
    main()
