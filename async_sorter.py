# async_sorter.py
"""
Asynchronous file sorter CLI tool.

Recursively scans a source folder and copies files to an output folder,
grouped by file extension.
"""

import argparse
import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional


# Sentinel object to signal end of queue
QUEUE_SENTINEL = object()


# Statistics
class Stats:
    """Track processing statistics."""

    def __init__(self) -> None:
        self.files_copied = 0
        self.files_skipped = 0
        self.files_failed = 0
        self.dirs_created = 0
        self.hidden_skipped = 0

    def __repr__(self) -> str:
        return (
            f"Stats(copied={self.files_copied}, skipped={self.files_skipped}, "
            f"failed={self.files_failed}, dirs_created={self.dirs_created}, "
            f"hidden_skipped={self.hidden_skipped})"
        )


async def async_rglob(path: Path, pattern: str):
    """
    Async wrapper for Path.rglob.

    Args:
        path: Directory to search
        pattern: Pattern to match

    Yields:
        Path objects matching the pattern
    """

    def _rglob():
        return list(path.rglob(pattern))

    results = await asyncio.to_thread(_rglob)
    for item in results:
        yield item


def _is_hidden_path(path: Path, src: Path) -> bool:
    """
    Check if any part of the path (relative to src) is hidden.

    Args:
        path: Path to check
        src: Source directory

    Returns:
        True if any part of the path is hidden (starts with .)
    """
    try:
        relative = path.relative_to(src)
        # Check all parts of the path
        for part in relative.parts:
            if part.startswith("."):
                return True
    except ValueError:
        # Path is not relative to src, check the name
        if path.name.startswith("."):
            return True
    return False


async def read_folder(
    src: Path,
    queue: asyncio.Queue[Path],
    include_hidden: bool,
    stats: Stats,
) -> None:
    """
    Recursively discover files and enqueue them for processing.

    Args:
        src: Source directory to scan
        queue: Queue to enqueue file paths
        include_hidden: Whether to include hidden files/directories
        stats: Statistics tracker
    """
    try:
        async for item in async_rglob(src, "*"):
            # Skip hidden files/directories if not included
            # Check if any part of the path is hidden
            if not include_hidden and _is_hidden_path(item, src):
                is_file = await asyncio.to_thread(item.is_file)
                if is_file:
                    stats.hidden_skipped += 1
                    logging.debug(f"Skipping hidden file: {item}")
                continue

            # Skip symlinks to avoid cycles
            is_symlink = await asyncio.to_thread(item.is_symlink)
            if is_symlink:
                logging.debug(f"Skipping symlink: {item}")
                continue

            # Only process regular files
            is_file = await asyncio.to_thread(item.is_file)
            if is_file:
                await queue.put(item)
                logging.debug(f"Enqueued file: {item}")

    except PermissionError as e:
        logging.error(f"Permission denied reading {src}: {e}")
    except Exception as e:
        logging.error(f"Error reading folder {src}: {e}")


def get_extension_group(path: Path) -> str:
    """
    Get normalized extension group name for a file path.

    Args:
        path: File path

    Returns:
        Extension group name (lowercase, no dot) or "no_ext"
    """
    ext = path.suffix.lower().lstrip(".")
    return ext if ext else "no_ext"


async def copy_file(
    src: Path,
    dst_root: Path,
    overwrite: bool,
    dry_run: bool,
    stats: Stats,
) -> None:
    """
    Copy a file to the appropriate extension subfolder.

    Args:
        src: Source file path
        dst_root: Root destination directory
        overwrite: Whether to overwrite existing files
        dry_run: If True, only log actions without copying
        stats: Statistics tracker
    """
    # Get extension group and build destination path early
    ext_group = get_extension_group(src)
    dst_dir = dst_root / ext_group
    dst_file = dst_dir / src.name

    try:
        # Ensure destination directory exists
        if not dry_run:
            dir_existed = await asyncio.to_thread(dst_dir.exists)
            await asyncio.to_thread(dst_dir.mkdir, parents=True, exist_ok=True)
            if not dir_existed:
                stats.dirs_created += 1
                logging.debug(f"Created directory: {dst_dir}")

        # Check if destination exists
        file_exists = await asyncio.to_thread(dst_file.exists)
        if file_exists and not overwrite:
            stats.files_skipped += 1
            logging.info(f"Skipped (exists): {src} -> {dst_file}")
            return

        # Perform copy
        if dry_run:
            logging.info(f"[DRY RUN] Would copy: {src} -> {dst_file}")
            stats.files_copied += 1
        else:
            # Use asyncio.to_thread for blocking I/O
            await asyncio.to_thread(shutil.copy2, str(src), str(dst_file))
            logging.info(f"Copied: {src} -> {dst_file}")
            stats.files_copied += 1

    except FileExistsError:
        stats.files_skipped += 1
        logging.warning(f"File already exists (overwrite=False): {dst_file}")
    except PermissionError as e:
        stats.files_failed += 1
        logging.error(f"Permission denied copying {src}: {e}")
    except Exception as e:
        stats.files_failed += 1
        logging.error(f"Error copying {src}: {e}", exc_info=True)


async def worker(
    queue: asyncio.Queue[Path],
    dst_root: Path,
    overwrite: bool,
    dry_run: bool,
    stats: Stats,
) -> None:
    """
    Worker coroutine that processes files from the queue.

    Args:
        queue: Queue containing file paths to process
        dst_root: Root destination directory
        overwrite: Whether to overwrite existing files
        dry_run: If True, only log actions without copying
        stats: Statistics tracker
    """
    while True:
        item = await queue.get()

        # Check for sentinel
        if item is QUEUE_SENTINEL:
            queue.task_done()
            break

        try:
            await copy_file(item, dst_root, overwrite, dry_run, stats)
        finally:
            queue.task_done()


async def main(
    source: str,
    output: str,
    workers: int,
    overwrite: bool,
    dry_run: bool,
    include_hidden: bool,
) -> None:
    """
    Main async function to orchestrate file sorting.

    Args:
        source: Source directory path
        output: Output directory path
        workers: Number of concurrent workers
        overwrite: Whether to overwrite existing files
        dry_run: If True, only log actions without copying
        include_hidden: Whether to include hidden files
    """
    src_path = Path(source)
    dst_path = Path(output)

    # Validate source exists
    src_exists = await asyncio.to_thread(src_path.exists)
    if not src_exists:
        logging.error(f"Source directory does not exist: {source}")
        return

    is_dir = await asyncio.to_thread(src_path.is_dir)
    if not is_dir:
        logging.error(f"Source is not a directory: {source}")
        return

    # Initialize statistics
    stats = Stats()

    # Create queue
    queue: asyncio.Queue[Path] = asyncio.Queue()

    logging.info(f"Starting file sort: {source} -> {output}")
    logging.info(f"Workers: {workers}, Overwrite: {overwrite}, Dry-run: {dry_run}")

    # Start producer task
    producer_task = asyncio.create_task(read_folder(src_path, queue, include_hidden, stats))

    # Start worker tasks
    worker_tasks = [
        asyncio.create_task(worker(queue, dst_path, overwrite, dry_run, stats))
        for _ in range(workers)
    ]

    # Wait for producer to finish
    await producer_task

    # Signal workers to stop
    for _ in range(workers):
        await queue.put(QUEUE_SENTINEL)

    # Wait for all tasks to complete
    await queue.join()

    # Cancel any remaining worker tasks (shouldn't be necessary, but safe)
    for task in worker_tasks:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # Log summary
    logging.info("=" * 60)
    logging.info("Processing complete!")
    logging.info(f"Files copied: {stats.files_copied}")
    logging.info(f"Files skipped: {stats.files_skipped}")
    logging.info(f"Files failed: {stats.files_failed}")
    logging.info(f"Hidden files skipped: {stats.hidden_skipped}")
    logging.info(f"Directories created: {stats.dirs_created}")
    logging.info("=" * 60)


def setup_logging(debug: bool) -> None:
    """Configure logging based on debug flag."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Asynchronously sort files by extension into subfolders."
    )
    parser.add_argument(
        "source",
        type=str,
        help="Source directory to scan",
    )
    parser.add_argument(
        "output",
        type=str,
        help="Output directory for sorted files",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=16,
        help="Maximum number of concurrent workers (default: 16)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files in destination",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not copy files, only log actions",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files and directories (starting with .)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG logging level",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.debug)

    try:
        asyncio.run(
            main(
                source=args.source,
                output=args.output,
                workers=args.workers,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
                include_hidden=args.include_hidden,
            )
        )
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
