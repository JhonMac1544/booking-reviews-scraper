thonimport json
import logging
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd
from xml.etree.ElementTree import Element, SubElement, ElementTree

logger = logging.getLogger("exporters")

def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

def _export_json(
    reviews: List[Dict],
    output_file: Path,
) -> Path:
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(reviews, f, indent=2, ensure_ascii=False)
    return output_file

def _export_tabular(
    reviews: List[Dict],
    output_file: Path,
    fmt: str,
) -> Path:
    df = pd.json_normalize(reviews)
    if fmt == "csv":
        df.to_csv(output_file, index=False)
    elif fmt == "excel":
        df.to_excel(output_file, index=False)
    elif fmt == "html":
        df.to_html(output_file, index=False)
    else:
        raise ValueError(f"Unsupported tabular format: {fmt}")
    return output_file

def _export_xml(
    reviews: List[Dict],
    output_file: Path,
) -> Path:
    root = Element("reviews")

    for record in reviews:
        review_el = SubElement(root, "review")
        for key, value in record.items():
            if isinstance(value, dict):
                nested_el = SubElement(review_el, key)
                for sub_key, sub_val in value.items():
                    leaf = SubElement(nested_el, sub_key)
                    leaf.text = "" if sub_val is None else str(sub_val)
            else:
                leaf = SubElement(review_el, key)
                leaf.text = "" if value is None else str(value)

    tree = ElementTree(root)
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return output_file

def export_reviews(
    reviews: Iterable[Dict],
    output_dir: Path | str,
    base_filename: str,
    formats: List[str],
) -> Dict[str, Path]:
    """
    Export reviews to multiple formats.

    Parameters
    ----------
    reviews: Iterable[Dict]
        Collection of review dictionaries to export.
    output_dir: Path | str
        Directory where output files will be written.
    base_filename: str
        Base file name without extension.
    formats: List[str]
        Formats to export, e.g. ["json", "csv", "excel", "xml", "html"].

    Returns
    -------
    Dict[str, Path]
        Mapping of format to the output file path.
    """
    if isinstance(output_dir, str):
        output_dir = Path(output_dir)

    _ensure_directory(output_dir)

    reviews_list = list(reviews)
    if not reviews_list:
        raise ValueError("No reviews provided for export.")

    export_map: Dict[str, Path] = {}
    normalized_formats = {fmt.lower() for fmt in formats}

    logger.debug(
        "Exporting %d reviews to formats: %s",
        len(reviews_list),
        ", ".join(sorted(normalized_formats)),
    )

    if "json" in normalized_formats:
        json_file = output_dir / f"{base_filename}.json"
        export_map["json"] = _export_json(reviews_list, json_file)

    for fmt in ("csv", "excel", "html"):
        if fmt in normalized_formats:
            ext = "csv" if fmt == "csv" else ("xlsx" if fmt == "excel" else "html")
            tabular_file = output_dir / f"{base_filename}.{ext}"
            export_map[fmt] = _export_tabular(reviews_list, tabular_file, fmt)

    if "xml" in normalized_formats:
        xml_file = output_dir / f"{base_filename}.xml"
        export_map["xml"] = _export_xml(reviews_list, xml_file)

    logger.info("Export completed. Files: %s", export_map)
    return export_map