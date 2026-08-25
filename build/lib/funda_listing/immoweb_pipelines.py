

import logging
import re
from collections import defaultdict

import attrs
from itemadapter import ItemAdapter

logger = logging.getLogger(__name__)

_EMPTY = (None, "", [], {})
_INDEX = re.compile(r"\[\d+\]")


def _is_filled(value) -> bool:
    return value not in _EMPTY


def _leaf_values(node, acc):
    """Every scalar value anywhere in the structure, stringified."""
    if isinstance(node, dict):
        for v in node.values():
            _leaf_values(v, acc)
    elif isinstance(node, list):
        for v in node:
            _leaf_values(v, acc)
    elif _is_filled(node):
        acc.add(str(node))
    return acc


def _leaf_paths(node, path="", out=None):
    """Every non-null scalar as {dotted.path: value}. List elements are
    indexed so siblings don't overwrite each other."""
    if out is None:
        out = {}
    if isinstance(node, dict):
        for k, v in node.items():
            _leaf_paths(v, f"{path}.{k}" if path else k, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _leaf_paths(v, f"{path}[{i}]", out)
    elif _is_filled(node):
        out[path] = node
    return out


class CoverageStatsPipeline:
    def __init__(self):
        self.count = 0
        self.filled = defaultdict(int)
        # Every key ever seen, filled or not. Counting only filled keys would
        # make a permanently-empty field invisible — the exact case this
        # report exists to surface.
        self.seen_keys = set()
        self.raw_checked = 0
        self.unmapped = defaultdict(int)

    # `spider` is optional: Scrapy 2.14 deprecates passing it and will drop
    # the argument in a future release.
    def process_item(self, item, spider=None):
        self.count += 1
        # Nested values are attrs instances (Address, Agent, PriceInfo...).
        # ItemAdapter hands them back as objects, and walking those would see
        # each one as a single opaque scalar — every nested field would then
        # look unmapped. Flatten to plain dicts first.
        if attrs.has(type(item)):
            data = attrs.asdict(item, recurse=True)
        else:
            data = ItemAdapter(item).asdict()
        raw = None

        for key, value in data.items():
            if key == "raw":
                raw = value
                continue
            if key == "feature" and isinstance(value, dict):
                for fk, fv in value.items():
                    name = f"feature.{fk}"
                    self.seen_keys.add(name)
                    if _is_filled(fv):
                        self.filled[name] += 1
                continue
            self.seen_keys.add(key)
            if _is_filled(value):
                self.filled[key] += 1

        if raw:
            self._check_unmapped(data, raw)
        return item

    def _check_unmapped(self, data, raw):
        """Compare every non-null source value against what we emitted."""
        self.raw_checked += 1
        emitted = _leaf_values(
            {k: v for k, v in data.items() if k != "raw"}, set()
        )
        for path, value in _leaf_paths(raw).items():
            text = str(value)
            # Some source values are normalised on the way out (e.g. document
            # `hash` arrives wrapped in literal quote characters), so compare
            # the cleaned form too rather than reporting a phantom gap.
            if text in emitted or text.strip('"') in emitted:
                continue
            self.unmapped[_INDEX.sub("[]", path)] += 1

    def close_spider(self, spider=None):
        if not self.count:
            logger.warning("coverage: no items scraped")
            return

        empty = [k for k in sorted(self.seen_keys) if self.filled[k] == 0]

        logger.info("=" * 62)
        logger.info(
            "FIELD COVERAGE over %d items — %d fields, %d empty on every item",
            self.count, len(self.seen_keys), len(empty),
        )
        logger.info("=" * 62)
        for key in sorted(self.seen_keys, key=lambda k: (-self.filled[k], k)):
            pct = 100.0 * self.filled[key] / self.count
            logger.info("  %-46s %6.1f%%  (%d)", key, pct, self.filled[key])

        if empty:
            logger.info(
                "empty on every item (usually null at source, not a bug — "
                "confirm with -a include_raw=1): %s",
                ", ".join(empty),
            )

        if not self.raw_checked:
            logger.info(
                "mapping check skipped: re-run with -a include_raw=1 to verify "
                "every source value reaches the output"
            )
        elif self.unmapped:
            logger.warning(
                "MAPPING GAP: %d source path(s) hold a value that never "
                "reaches the output (checked %d items): %s",
                len(self.unmapped), self.raw_checked,
                ", ".join(
                    f"{p} ({c}x)"
                    for p, c in sorted(self.unmapped.items(), key=lambda x: -x[1])
                ),
            )
        else:
            logger.info(
                "mapping verified: every non-null source value reaches the "
                "output across %d items", self.raw_checked,
            )
        logger.info("=" * 62)
