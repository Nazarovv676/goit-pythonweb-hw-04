# tests/test_async_sorter.py
"""Tests for async_sorter module."""

import asyncio
import shutil
from pathlib import Path

import pytest

from async_sorter import (
    copy_file,
    get_extension_group,
    main,
    read_folder,
    Stats,
    worker,
    QUEUE_SENTINEL,
)


class TestGetExtensionGroup:
    """Tests for get_extension_group function."""

    def test_with_extension(self):
        """Test files with extensions."""
        assert get_extension_group(Path("file.txt")) == "txt"
        assert get_extension_group(Path("file.JPG")) == "jpg"
        assert get_extension_group(Path("file.PDF")) == "pdf"
        assert get_extension_group(Path("file.tar.gz")) == "gz"

    def test_no_extension(self):
        """Test files without extensions."""
        assert get_extension_group(Path("file")) == "no_ext"
        assert get_extension_group(Path("file.")) == "no_ext"

    def test_multiple_dots(self):
        """Test files with multiple dots."""
        assert get_extension_group(Path("file.backup.txt")) == "txt"


@pytest.mark.asyncio
async def test_read_folder_basic(tmp_path):
    """Test reading a folder with various files."""
    # Create test structure
    (tmp_path / "file1.txt").write_text("content1")
    (tmp_path / "file2.jpg").write_text("content2")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "file3.pdf").write_text("content3")

    queue = asyncio.Queue()
    stats = Stats()
    src = Path(tmp_path)

    await read_folder(src, queue, include_hidden=False, stats=stats)

    # Collect all items from queue
    items = []
    while not queue.empty():
        items.append(await queue.get())

    # Should have 3 files
    assert len(items) == 3
    file_names = {item.name for item in items}
    assert file_names == {"file1.txt", "file2.jpg", "file3.pdf"}


@pytest.mark.asyncio
async def test_read_folder_hidden_files(tmp_path):
    """Test that hidden files are skipped by default."""
    (tmp_path / "file1.txt").write_text("content1")
    (tmp_path / ".hidden").write_text("hidden")
    (tmp_path / ".hidden_dir").mkdir()
    (tmp_path / ".hidden_dir" / "file2.txt").write_text("content2")

    queue = asyncio.Queue()
    stats = Stats()
    src = Path(tmp_path)

    await read_folder(src, queue, include_hidden=False, stats=stats)

    items = []
    while not queue.empty():
        items.append(await queue.get())

    # Should only have non-hidden file
    assert len(items) == 1
    assert items[0].name == "file1.txt"
    assert stats.hidden_skipped >= 1


@pytest.mark.asyncio
async def test_read_folder_include_hidden(tmp_path):
    """Test that hidden files are included when flag is set."""
    (tmp_path / "file1.txt").write_text("content1")
    (tmp_path / ".hidden").write_text("hidden")

    queue = asyncio.Queue()
    stats = Stats()
    src = Path(tmp_path)

    await read_folder(src, queue, include_hidden=True, stats=stats)

    items = []
    while not queue.empty():
        items.append(await queue.get())

    # Should have both files
    assert len(items) == 2
    file_names = {item.name for item in items}
    assert file_names == {"file1.txt", ".hidden"}


@pytest.mark.asyncio
async def test_copy_file_basic(tmp_path):
    """Test copying a file to the correct extension folder."""
    src_file = tmp_path / "source" / "test.txt"
    src_file.parent.mkdir()
    src_file.write_text("test content")

    dst_root = Path(tmp_path / "output")
    stats = Stats()

    await copy_file(
        Path(src_file),
        dst_root,
        overwrite=False,
        dry_run=False,
        stats=stats,
    )

    # Check file was copied
    dst_file = dst_root / "txt" / "test.txt"
    assert dst_file.exists()
    assert dst_file.read_text() == "test content"
    assert stats.files_copied == 1


@pytest.mark.asyncio
async def test_copy_file_no_extension(tmp_path):
    """Test copying a file without extension goes to no_ext."""
    src_file = tmp_path / "source" / "noext"
    src_file.parent.mkdir()
    src_file.write_text("content")

    dst_root = Path(tmp_path / "output")
    stats = Stats()

    await copy_file(
        Path(src_file),
        dst_root,
        overwrite=False,
        dry_run=False,
        stats=stats,
    )

    # Check file was copied to no_ext
    dst_file = dst_root / "no_ext" / "noext"
    assert dst_file.exists()
    assert stats.files_copied == 1


@pytest.mark.asyncio
async def test_copy_file_overwrite(tmp_path):
    """Test overwrite behavior."""
    src_file = tmp_path / "source" / "test.txt"
    src_file.parent.mkdir()
    src_file.write_text("new content")

    dst_root = Path(tmp_path / "output")
    dst_file = dst_root / "txt" / "test.txt"
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    dst_file.write_text("old content")

    stats = Stats()

    # Without overwrite
    await copy_file(
        Path(src_file),
        dst_root,
        overwrite=False,
        dry_run=False,
        stats=stats,
    )

    # File should not be overwritten
    assert dst_file.read_text() == "old content"
    assert stats.files_skipped == 1

    # With overwrite
    stats2 = Stats()
    await copy_file(
        Path(src_file),
        dst_root,
        overwrite=True,
        dry_run=False,
        stats=stats2,
    )

    # File should be overwritten
    assert dst_file.read_text() == "new content"
    assert stats2.files_copied == 1


@pytest.mark.asyncio
async def test_copy_file_dry_run(tmp_path):
    """Test dry run mode doesn't actually copy files."""
    src_file = tmp_path / "source" / "test.txt"
    src_file.parent.mkdir()
    src_file.write_text("content")

    dst_root = Path(tmp_path / "output")
    stats = Stats()

    await copy_file(
        Path(src_file),
        dst_root,
        overwrite=False,
        dry_run=True,
        stats=stats,
    )

    # File should not exist
    dst_file = dst_root / "txt" / "test.txt"
    assert not dst_file.exists()
    # But stats should show it as copied (for dry run)
    assert stats.files_copied == 1


@pytest.mark.asyncio
async def test_worker(tmp_path):
    """Test worker coroutine processes files from queue."""
    # Create source files
    (tmp_path / "source" / "file1.txt").parent.mkdir()
    (tmp_path / "source" / "file1.txt").write_text("content1")
    (tmp_path / "source" / "file2.jpg").write_text("content2")

    queue = asyncio.Queue()
    dst_root = Path(tmp_path / "output")
    stats = Stats()

    # Enqueue files
    await queue.put(Path(tmp_path / "source" / "file1.txt"))
    await queue.put(Path(tmp_path / "source" / "file2.jpg"))
    await queue.put(QUEUE_SENTINEL)

    # Run worker
    await worker(queue, dst_root, overwrite=False, dry_run=False, stats=stats)

    # Check files were copied
    assert (dst_root / "txt" / "file1.txt").exists()
    assert (dst_root / "jpg" / "file2.jpg").exists()
    assert stats.files_copied == 2


@pytest.mark.asyncio
async def test_main_integration(tmp_path):
    """Integration test for main function."""
    # Create test structure
    src_dir = tmp_path / "source"
    src_dir.mkdir()

    (src_dir / "file1.txt").write_text("text content")
    (src_dir / "file2.jpg").write_text("image content")
    (src_dir / "file3").write_text("no extension")
    (src_dir / "subdir").mkdir()
    (src_dir / "subdir" / "file4.pdf").write_text("pdf content")

    dst_dir = tmp_path / "output"

    await main(
        source=str(src_dir),
        output=str(dst_dir),
        workers=4,
        overwrite=False,
        dry_run=False,
        include_hidden=False,
    )

    # Verify organization
    assert (dst_dir / "txt" / "file1.txt").exists()
    assert (dst_dir / "jpg" / "file2.jpg").exists()
    assert (dst_dir / "no_ext" / "file3").exists()
    assert (dst_dir / "pdf" / "file4.pdf").exists()

    # Verify content
    assert (dst_dir / "txt" / "file1.txt").read_text() == "text content"
    assert (dst_dir / "jpg" / "file2.jpg").read_text() == "image content"
    assert (dst_dir / "no_ext" / "file3").read_text() == "no extension"
    assert (dst_dir / "pdf" / "file4.pdf").read_text() == "pdf content"


@pytest.mark.asyncio
async def test_main_dry_run(tmp_path):
    """Test main function in dry run mode."""
    src_dir = tmp_path / "source"
    src_dir.mkdir()
    (src_dir / "file1.txt").write_text("content")

    dst_dir = tmp_path / "output"

    await main(
        source=str(src_dir),
        output=str(dst_dir),
        workers=2,
        overwrite=False,
        dry_run=True,
        include_hidden=False,
    )

    # Files should not be copied in dry run
    assert not (dst_dir / "txt" / "file1.txt").exists()


@pytest.mark.asyncio
async def test_main_hidden_files(tmp_path):
    """Test main function with hidden files."""
    src_dir = tmp_path / "source"
    src_dir.mkdir()
    (src_dir / "file1.txt").write_text("visible")
    (src_dir / ".hidden").write_text("hidden")

    dst_dir = tmp_path / "output"

    # Without include_hidden
    await main(
        source=str(src_dir),
        output=str(dst_dir),
        workers=2,
        overwrite=False,
        dry_run=False,
        include_hidden=False,
    )

    assert (dst_dir / "txt" / "file1.txt").exists()
    assert not (dst_dir / "no_ext" / ".hidden").exists()

    # Clear output and test with include_hidden
    shutil.rmtree(dst_dir)

    await main(
        source=str(src_dir),
        output=str(dst_dir),
        workers=2,
        overwrite=False,
        dry_run=False,
        include_hidden=True,
    )

    assert (dst_dir / "txt" / "file1.txt").exists()
    assert (dst_dir / "no_ext" / ".hidden").exists()
