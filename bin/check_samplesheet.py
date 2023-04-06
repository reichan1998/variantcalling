#!/usr/bin/env python

"""Provide a command line tool to validate and transform tabular samplesheets."""


import argparse
import csv
import logging
import sys
from collections import Counter
from pathlib import Path

logger = logging.getLogger()


class RowChecker:
    """
    Define a service that can validate and transform each given row.

    Attributes:
        modified (list): A list of dicts, where each dict corresponds to a previously
            validated and transformed row. The order of rows is maintained.

    """

    DATA_VALID_FORMATS = (
        ".cram",
        ".bam",
    )

    VALID_DATATYPES = ("pacbio",)

    def __init__(
        self,
        sample_col="sample",
        type_col="datatype",
        file_col="datafile",
        index_col="indexfile",
        **kwargs,
    ):
        """
        Initialize the row checker with the expected column names.

        Args:
            sample_col (str): The name of the column that contains the sample name
                (default "sample").
            type_col (str): The name of the column that contains the dataype for
                the read data (default "datatype").
            file_col (str): The name of the column that contains the file path for
                the read data (default "datafile").
            index_col (str): The name of the column that contains the index file
                for the data (default "indexfile").

        """
        super().__init__(**kwargs)

        self._sample_col = sample_col
        self._type_col = type_col
        self._file_col = file_col
        self._index_col = index_col
        self._seen = set()
        self.modified = []

    def validate_and_transform(self, row):
        """
        Perform all validations on the given row.

        Args:
            row (dict): A mapping from column headers (keys) to elements of that row
                (values).

        """
        self._validate_sample(row)
        self._validate_type(row)
        self._validate_data_file(row)
        self._validate_index_file(row)
        self._seen.add((row[self._sample_col], row[self._file_col]))
        self.modified.append(row)

    def _validate_sample(self, row):
        """Assert that the sample name exists and convert spaces to underscores."""
        if len(row[self._sample_col]) <= 0:
            raise AssertionError("Sample input is required.")
        # Sanitize samples slightly.
        row[self._sample_col] = row[self._sample_col].replace(" ", "_")

    def _validate_type(self, row):
        """Assert that the data type matches expected values."""
        if not any(row[self._type_col] for datatype in self.VALID_DATATYPES):
            raise AssertionError(
                f"The datatype is unrecognized: {row[self._type_col]}\n"
                f"It should be one of: {', '.join(self.VALID_DATATYPES)}"
            )

    def _validate_data_file(self, row):
        """Assert that the datafile is non-empty and has the right format."""
        if len(row[self._file_col]) <= 0:
            raise AssertionError("Data file is required.")
        self._validate_data_format(row[self._file_col])

    def _validate_index_file(self, row):
        """Assert that the indexfile is non-empty and has the right format."""
        if len(row[self._index_col]) <= 0:
            raise AssertionError("Data index file is required.")
        if row[self._file_col].endswith("bam") and not row[self._index_col].endswith("bai"):
            raise AssertionError("bai index file should be given for bam file.")
        if row[self._file_col].endswith("cram") and not row[self._index_col].endswith("crai"):
            raise AssertionError("crai index file shuld be given for cram file.")

    def _validate_data_format(self, filename):
        """Assert that a given filename has one of the expected read data file extensions."""
        if not any(filename.endswith(extension) for extension in self.DATA_VALID_FORMATS):
            raise AssertionError(
                f"The data file has an unrecognized extension: {filename}\n"
                f"It should be one of: {', '.join(self.DATA_VALID_FORMATS)}"
            )

    def validate_unique_samples(self):
        """
        Assert that the combination of sample name and data filename is unique.

        In addition to the validation, also rename all samples to have a suffix of _T{n}, where n is the
        number of times the same sample exist, but with different files, e.g., multiple runs per experiment.

        """
        if len(self._seen) != len(self.modified):
            raise AssertionError("The combination of sample name and data file must be unique.")
        seen = Counter()
        for row in self.modified:
            sample = row[self._sample_col]
            seen[sample] += 1
            row[self._sample_col] = f"{sample}_T{seen[sample]}"


def read_head(handle, num_lines=10):
    """Read the specified number of lines from the current position in the file."""
    lines = []
    for idx, line in enumerate(handle):
        if idx == num_lines:
            break
        lines.append(line)
    return "".join(lines)


def sniff_format(handle):
    """
    Detect the tabular format.

    Args:
        handle (text file): A handle to a `text file`_ object. The read position is
        expected to be at the beginning (index 0).

    Returns:
        csv.Dialect: The detected tabular format.

    .. _text file:
        https://docs.python.org/3/glossary.html#term-text-file

    """
    peek = read_head(handle)
    handle.seek(0)
    sniffer = csv.Sniffer()
    # same input file could retrun random true or false
    # disable it now
    # the following validation should be enough
    # if not sniffer.has_header(peek):
    #    logger.critical("The given sample sheet does not appear to contain a header.")
    #    sys.exit(1)
    dialect = sniffer.sniff(peek)
    return dialect


def check_samplesheet(file_in, file_out):
    """
    Check that the tabular samplesheet has the structure expected by nf-core pipelines.

    Validate the general shape of the table, expected columns, and each row.

    Args:
        file_in (pathlib.Path): The given tabular samplesheet. The format can be either
            CSV, TSV, or any other format automatically recognized by ``csv.Sniffer``.
        file_out (pathlib.Path): Where the validated and transformed samplesheet should
            be created; always in CSV format.

    Example:
        This function checks that the samplesheet follows the following structure,
        see also the `variantcalling samplesheet`_::

            sample,datatype,datafile,indexfile
            sample1,pacbio,/path/to/data/file/file1.bam,/path/to/index/file/file1.bai
            sample2,pacbio,/path/to/data/file/file2.cram,/path/to/index/file/file2.crai

    .. _variantcalling samplesheet:
        https://raw.githubusercontent.com/sanger-tol/variantcalling/main/assets/samplesheet.csv

    """
    required_columns = {"sample", "datatype", "datafile", "indexfile"}
    # See https://docs.python.org/3.9/library/csv.html#id3 to read up on `newline=""`.
    with file_in.open(newline="") as in_handle:
        reader = csv.DictReader(in_handle, dialect=sniff_format(in_handle))
        # Validate the existence of the expected header columns.
        if not required_columns.issubset(reader.fieldnames):
            req_cols = ", ".join(required_columns)
            logger.critical(f"The sample sheet **must** contain these column headers: {req_cols}.")
            sys.exit(1)
        # Validate each row.
        checker = RowChecker()
        for i, row in enumerate(reader):
            try:
                checker.validate_and_transform(row)
            except AssertionError as error:
                logger.critical(f"{str(error)} On line {i + 2}.")
                sys.exit(1)
        checker.validate_unique_samples()
    header = list(reader.fieldnames)
    # See https://docs.python.org/3.9/library/csv.html#id3 to read up on `newline=""`.
    with file_out.open(mode="w", newline="") as out_handle:
        writer = csv.DictWriter(out_handle, header, delimiter=",")
        writer.writeheader()
        for row in checker.modified:
            writer.writerow(row)


def parse_args(argv=None):
    """Define and immediately parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate and transform a tabular samplesheet.",
        epilog="Example: python check_samplesheet.py samplesheet.csv samplesheet.valid.csv",
    )
    parser.add_argument(
        "file_in",
        metavar="FILE_IN",
        type=Path,
        help="Tabular input samplesheet in CSV or TSV format.",
    )
    parser.add_argument(
        "file_out",
        metavar="FILE_OUT",
        type=Path,
        help="Transformed output samplesheet in CSV format.",
    )
    parser.add_argument(
        "-l",
        "--log-level",
        help="The desired log level (default WARNING).",
        choices=("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"),
        default="WARNING",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version="%(prog)s 1.0",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """Coordinate argument parsing and program execution."""
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level, format="[%(levelname)s] %(message)s")
    if not args.file_in.is_file():
        logger.error(f"The given input file {args.file_in} was not found!")
        sys.exit(2)
    args.file_out.parent.mkdir(parents=True, exist_ok=True)
    check_samplesheet(args.file_in, args.file_out)


if __name__ == "__main__":
    sys.exit(main())
