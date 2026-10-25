"""Contract tests for the local PKLot exploration pipeline."""

import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from tarfile import TarInfo
from tarfile import open as open_tar

import pytest
from PIL import Image

from data.pklot_parser import AnnotationError, parse_pklot_xml
from data.validation import audit_archive, audit_directory, validate_pair


def xml_sample(camera: str = "UFPR04", label: str = "1") -> bytes:
    return (
        f'<parking id="{camera}">'
        f'<space id="1" occupied="{label}">'
        '<rotatedRect><center x="15" y="15" /></rotatedRect>'
        '<contour><point x="10" y="10"/><point x="20" y="10"/>'
        '<point x="20" y="20"/><point x="10" y="20"/></contour>'
        "</space>"
        '<space id="2" occupied="0">'
        '<contour><point x="30" y="30"/><point x="40" y="30"/>'
        '<point x="40" y="40"/><point x="30" y="40"/></contour>'
        "</space></parking>"
    ).encode()


def jpeg_sample() -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 48), "white").save(output, format="JPEG")
    return output.getvalue()


def test_parse_pklot_xml_preserves_real_fields_with_flexible_path() -> None:
    parsed = parse_pklot_xml(
        xml_sample(camera="ufpr04"),
        "arbitrary/nesting/UFPR04/Rainy/2012-12-21/frame.xml",
    )

    assert parsed.camera_id == "UFPR04"
    assert parsed.capture_day == "2012-12-21"
    assert [(spot.spot_id, spot.occupied) for spot in parsed.spots] == [
        ("1", True),
        ("2", False),
    ]
    assert parsed.spots[0].polygon == ((10, 10), (20, 10), (20, 20), (10, 20))


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"<annotations />", "Unsupported XML root"),
        (xml_sample(label="unknown"), "occupied"),
        (xml_sample().replace(b'x="20" y="20"', b'x="10" y="10"'), "polygon"),
        (xml_sample().replace(b'id="2"', b'id="1"'), "duplicate"),
        (
            xml_sample().replace(b"</space>", b"<unrecognized /></space>", 1),
            "Unsupported",
        ),
    ],
)
def test_parser_rejects_unsupported_or_invalid_ground_truth(
    content: bytes, expected: str
) -> None:
    with pytest.raises(AnnotationError, match=expected):
        parse_pklot_xml(content, "camera/2012-12-21/frame.xml")


def test_validate_pair_checks_image_decode_and_polygon_bounds() -> None:
    source = "random/2012-12-21/frame.xml"
    valid = validate_pair(jpeg_sample(), xml_sample(), source)
    assert (valid.width, valid.height, valid.empty_count, valid.occupied_count) == (
        64,
        48,
        1,
        1,
    )

    with pytest.raises(ValueError, match="decode"):
        validate_pair(b"not an image", xml_sample(), source)
    outside = xml_sample().replace(b'x="40"', b'x="80"')
    with pytest.raises(ValueError, match="outside"):
        validate_pair(jpeg_sample(), outside, source)


def test_parser_rejects_camera_mismatch_in_identified_pklot_path() -> None:
    with pytest.raises(AnnotationError, match="camera"):
        parse_pklot_xml(
            xml_sample(camera="PUCPR"),
            "other/layout/UFPR04/Rainy/2012-12-21/frame.xml",
        )


def test_directory_audit_reports_valid_missing_and_corrupt_pairs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "unusual" / "collection"
    frames = root / "camera_group" / "2012-12-21"
    frames.mkdir(parents=True)
    (frames / "good.jpg").write_bytes(jpeg_sample())
    (frames / "good.xml").write_bytes(xml_sample())
    (frames / "missing_image.xml").write_bytes(xml_sample())
    (frames / "orphan.jpg").write_bytes(jpeg_sample())
    (frames / "corrupt.jpg").write_bytes(b"bad")
    (frames / "corrupt.xml").write_bytes(xml_sample())
    unlabeled_day = root / "camera_group" / "2012-12-22"
    unlabeled_day.mkdir()
    (unlabeled_day / "lone.jpg").write_bytes(jpeg_sample())
    # Segmented crops without XML must not be treated as missing full-frame labels.
    crops = root / "PKLotSegmented" / "UFPR04" / "Occupied"
    crops.mkdir(parents=True)
    (crops / "crop.jpg").write_bytes(jpeg_sample())

    report = audit_directory(root, tmp_path / "output", max_samples=0, overlays=1)

    assert report["scope"] == "complete"
    assert report["xml_files_seen"] == 3
    assert report["image_files_seen"] == 4
    assert report["valid_pairs"] == 1
    assert report["class_counts"] == {"empty": 1, "occupied": 1}
    assert report["camera_counts"] == {"UFPR04": 1}
    assert report["day_counts"] == {"2012-12-21": 1}
    assert report["dimension_counts"] == {"64x48": 1}
    assert {error["code"] for error in report["errors"]} == {
        "MISSING_IMAGE",
        "MISSING_ANNOTATION",
        "CORRUPT_IMAGE",
    }
    assert sum(error["code"] == "MISSING_ANNOTATION" for error in report["errors"]) == 2
    assert (tmp_path / "output" / "stats.json").exists()
    assert (tmp_path / "output" / "samples.csv").exists()
    assert (
        ",UFPR04,2012-12-21,64,48,1,1"
        in (tmp_path / "output" / "samples.csv").read_text()
    )
    assert (tmp_path / "output" / "errors.csv").exists()
    with Image.open(tmp_path / "output" / "overlays" / "001.png") as overlay:
        red, green, blue = overlay.getpixel((10, 10))
        assert red > green and red > blue


def test_archive_audit_pairs_image_before_xml_without_extracting(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "local.tar.gz"
    stem = "outer/nested/UFPR04/Rainy/2012-12-21/frame"
    with open_tar(archive_path, "w:gz") as archive:
        for name, content in (
            (f"{stem}.jpg", jpeg_sample()),
            (f"{stem}.xml", xml_sample()),
        ):
            entry = TarInfo(name)
            entry.size = len(content)
            archive.addfile(entry, BytesIO(content))

    report = audit_archive(archive_path, tmp_path / "output", max_samples=1)

    assert report["scope"] == "sample"
    assert report["valid_pairs"] == 1
    assert report["class_counts"] == {"empty": 1, "occupied": 1}
    assert report["errors"] == []


def test_inspection_script_uses_configured_dataset_root(tmp_path: Path) -> None:
    root = tmp_path / "my-local-dataset" / "2012-12-21"
    root.mkdir(parents=True)
    (root / "frame.jpg").write_bytes(jpeg_sample())
    (root / "frame.xml").write_bytes(xml_sample())
    output = tmp_path / "report"
    script = Path(__file__).parents[1] / "scripts" / "inspect_dataset.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(root.parent),
            "--output-dir",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads((output / "stats.json").read_text())["valid_pairs"] == 1
