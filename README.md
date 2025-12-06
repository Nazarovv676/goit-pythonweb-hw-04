# Async File Sorter

A production-ready, asynchronous CLI tool for sorting files by extension. Recursively scans a source directory and copies files into an output directory, organized into subfolders by file extension.

## Features

- **Asynchronous processing**: High-performance concurrent file operations using `asyncio`
- **Extension-based organization**: Files grouped into subfolders by extension (lowercase, no dot)
- **Robust error handling**: Continues processing even when individual files fail
- **Comprehensive logging**: Detailed logs at INFO and DEBUG levels
- **Flexible options**: Control concurrency, overwrite behavior, hidden files, and dry-run mode

## Requirements

- Python ≥ 3.11
- Poetry (for dependency management)

## Installation

1. Clone or download this repository

2. Install dependencies using Poetry:
```bash
poetry install
```

Alternatively, if you prefer using pip:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

### Basic Usage

```bash
python async_sorter.py /path/to/source /path/to/output
```

### Advanced Options

```bash
# Use 32 workers, overwrite existing files, enable debug logging
python async_sorter.py /path/to/source /path/to/output --workers 32 --overwrite --debug

# Dry run to see what would be copied without actually copying
python async_sorter.py /path/to/source /path/to/output --dry-run

# Include hidden files (starting with .)
python async_sorter.py /path/to/source /path/to/output --include-hidden
```

### Command-Line Arguments

- `source` (required): Source directory to scan recursively
- `output` (required): Output directory for sorted files
- `--workers` (default: 16): Maximum number of concurrent workers
- `--overwrite`: Overwrite existing files in destination
- `--dry-run`: Do not copy files, only log actions
- `--include-hidden`: Include hidden files and directories (starting with `.`)
- `--debug`: Enable DEBUG logging level

## File Organization

Files are organized into subfolders based on their extension:

- Files with extension `.jpg` → `output/jpg/`
- Files with extension `.txt` → `output/txt/`
- Files with extension `.PDF` → `output/pdf/` (normalized to lowercase)
- Files without extension → `output/no_ext/`

Extensions are normalized to lowercase and the leading dot is removed.

## Examples

### Example 1: Basic Sort

```bash
python async_sorter.py ~/Downloads ~/SortedFiles
```

This will:
- Scan `~/Downloads` recursively
- Copy all files to `~/SortedFiles` organized by extension
- Use 16 concurrent workers (default)
- Skip existing files (unless `--overwrite` is used)

### Example 2: Dry Run

```bash
python async_sorter.py . ./sorted --dry-run
```

This will show what would be copied without actually copying files.

### Example 3: High Concurrency

```bash
python async_sorter.py /large/directory /output --workers 64 --overwrite
```

Useful for processing large directories with many files.

## Performance

- **Concurrency**: The `--workers` parameter controls how many files are copied simultaneously. Higher values can improve performance on systems with fast I/O, but may be limited by disk speed or system resources.
- **Scalability**: Designed to handle large directories efficiently through asynchronous I/O and concurrent processing.
- **Memory**: Memory usage is kept low by processing files one at a time per worker, rather than loading all files into memory.

## Limitations

- **Symlinks**: Symlinks are skipped to avoid cycles. If you need to follow symlinks, the code would need modification.
- **Permissions**: Files that cannot be read or written due to permissions will be logged as errors but won't stop the process.
- **Long paths**: On Windows, very long paths (>260 characters) may cause issues unless long path support is enabled.

## Troubleshooting

### Permission Errors

If you encounter permission errors:
- Ensure you have read access to the source directory
- Ensure you have write access to the output directory
- On Unix-like systems, you may need to use `sudo` (though this is generally not recommended)

### Files Not Being Copied

- Check that files aren't being skipped due to `--include-hidden` not being set (if files start with `.`)
- Verify that `--overwrite` is set if destination files already exist
- Review logs with `--debug` to see detailed decision-making

### Performance Issues

- Adjust `--workers` based on your system capabilities
- On systems with slow disks, lower worker counts may perform better
- Use `--dry-run` first to estimate the scope of work

## Testing

Run tests using pytest:

```bash
poetry run pytest
```

Or with pip:

```bash
pytest tests/
```

## Code Style

The code follows PEP 8 and is formatted with Black. Format the code with:

```bash
poetry run black .
```

Or:

```bash
black .
```

## License

This project is provided as-is for educational and production use.

