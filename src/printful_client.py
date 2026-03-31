"""
Printful REST API v1 wrapper for uploading designs and creating products.

Usage:
    client = PrintfulClient(api_key="...")
    file_id = client.upload_file(Path("output/png/Lake Polly.png"))
    product_id = client.find_bella_canvas_3001()
    variants  = client.get_asphalt_variants(product_id)
    mockups   = client.generate_mockup(product_id, [v["variant_id"] for v in variants], file_id)
    sync_id   = client.create_sync_product("Lake Polly BWCA T-Shirt", file_id, variants)
"""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path

import requests

from .config import PRINTFUL_API_BASE, PRINTFUL_API_KEY

logger = logging.getLogger(__name__)

REQUEST_DELAY = 0.5  # seconds between API calls (120 req/min limit)


class PrintfulError(Exception):
    pass


class PrintfulClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or PRINTFUL_API_KEY
        if not self.api_key:
            raise ValueError(
                "Printful API key not set. Add PRINTFUL_API_KEY to your .env file."
            )
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        # Cached catalog data
        self._product_id: int | None = None
        self._variants: list[dict] | None = None

    # ── Low-level helpers ────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kwargs) -> dict:
        time.sleep(REQUEST_DELAY)
        url = f"{PRINTFUL_API_BASE}{path}"
        resp = self.session.request(method, url, **kwargs)
        if resp.status_code >= 400:
            raise PrintfulError(
                f"{method} {path} → {resp.status_code}: {resp.text[:500]}"
            )
        return resp.json()

    def _get(self, path: str, **kw) -> dict:
        return self._request("GET", path, **kw)

    def _post(self, path: str, **kw) -> dict:
        return self._request("POST", path, **kw)

    # ── Catalog ──────────────────────────────────────────────────────────

    def find_bella_canvas_3001(self) -> int:
        """Return the Printful product_id for Bella+Canvas 3001."""
        if self._product_id:
            return self._product_id

        data = self._get("/products")
        for product in data.get("result", []):
            model = product.get("model", "")
            if "3001" in model and "3001" in product.get("type", model):
                self._product_id = product["id"]
                logger.info("Bella+Canvas 3001 → product_id %d", product["id"])
                return product["id"]

        raise PrintfulError(
            "Could not find Bella+Canvas 3001 in the Printful catalog."
        )

    def get_asphalt_variants(self, product_id: int | None = None) -> list[dict]:
        """Return variant dicts [{variant_id, size, color}] for Asphalt colour."""
        if self._variants:
            return self._variants

        pid = product_id or self.find_bella_canvas_3001()
        data = self._get(f"/products/{pid}")
        variants = []
        for v in data.get("result", {}).get("variants", []):
            if "asphalt" in v.get("color", "").lower():
                variants.append({
                    "variant_id": v["id"],
                    "size": v.get("size", ""),
                    "color": v.get("color", ""),
                })

        if not variants:
            raise PrintfulError(
                f"No Asphalt variants found for product {pid}. "
                "Check the Printful catalog for available colours."
            )

        self._variants = variants
        logger.info("Found %d Asphalt variants (sizes: %s)",
                     len(variants),
                     ", ".join(v["size"] for v in variants))
        return variants

    # ── File upload ──────────────────────────────────────────────────────

    def upload_file(self, png_path: Path, filename: str | None = None) -> int:
        """Upload a PNG to Printful's file library. Returns the file ID."""
        if filename is None:
            filename = png_path.name

        with open(png_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")

        data = self._post("/files", json={
            "type": "default",
            "url": f"data:image/png;base64,{b64}",
            "filename": filename,
            "visible": True,
        })

        file_id = data["result"]["id"]
        logger.info("Uploaded %s → file_id %d", filename, file_id)
        return file_id

    # ── Mockup generation ────────────────────────────────────────────────

    def generate_mockup(
        self,
        product_id: int,
        variant_ids: list[int],
        file_id: int,
        *,
        timeout: int = 120,
    ) -> list[str]:
        """
        Start a mockup generation task and poll until complete.
        Returns a list of mockup image URLs.
        """
        payload = {
            "variant_ids": variant_ids[:3],  # limit to 3 mockups
            "files": [{"placement": "front", "image_url": f"printful-file:{file_id}"}],
        }
        task = self._post(
            f"/mockup-generator/create-task/{product_id}", json=payload
        )
        task_key = task["result"]["task_key"]
        logger.info("Mockup task started: %s", task_key)

        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(3)
            status = self._get(f"/mockup-generator/task?task_key={task_key}")
            result = status.get("result", {})
            if result.get("status") == "completed":
                urls = [m["mockup_url"] for m in result.get("mockups", [])]
                logger.info("Mockup complete: %d images", len(urls))
                return urls
            if result.get("status") == "failed":
                raise PrintfulError(f"Mockup failed: {result.get('error')}")

        raise PrintfulError("Mockup generation timed out")

    # ── Product creation ─────────────────────────────────────────────────

    def create_sync_product(
        self,
        product_name: str,
        file_id: int,
        variants: list[dict] | None = None,
        thumbnail_url: str | None = None,
    ) -> int:
        """
        Create a store sync-product with all Asphalt size variants.
        Returns the sync_product_id.
        """
        if variants is None:
            variants = self.get_asphalt_variants()

        sync_variants = []
        for v in variants:
            sv = {
                "variant_id": v["variant_id"],
                "retail_price": "29.99",
                "files": [
                    {"id": file_id, "type": "front"},
                ],
            }
            sync_variants.append(sv)

        payload: dict = {
            "sync_product": {"name": product_name},
            "sync_variants": sync_variants,
        }
        if thumbnail_url:
            payload["sync_product"]["thumbnail"] = thumbnail_url

        data = self._post("/store/products", json=payload)
        sync_id = data["result"]["id"]
        logger.info("Created sync product '%s' → id %d", product_name, sync_id)
        return sync_id
