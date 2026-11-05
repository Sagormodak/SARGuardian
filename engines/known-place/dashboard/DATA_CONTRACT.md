# Web Dashboard Data Contract

The generated viewer must consume a versioned manifest, not discover files by filename heuristics alone.

## Top-level manifest

```json
{
  "schema_version": "sarguardian-web-dashboard/1.0",
  "run": {
    "github_run_id": "...",
    "generated_at_utc": "...",
    "aoi_wkt_sha256": "...",
    "science_commit": "...",
    "orchestration_commit": "..."
  },
  "validation": {
    "processing_status": "PASS",
    "visual_assets_status": "PASS",
    "independent_geophysical_validation": "NOT_PERFORMED"
  },
  "aoi": {
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": []},
    "crs": "EPSG:4326"
  },
  "observations": [
    {
      "id": "GUNW-003",
      "product_type": "GUNW",
      "granule_name": "...",
      "reference_date": "YYYY-MM-DD",
      "secondary_date": "YYYY-MM-DD",
      "track": "DESC 091",
      "maturity": "PROVISIONAL",
      "bands": [
        {
          "band": 1,
          "description": "LOS displacement (mm)",
          "units": "mm",
          "native_asset": "product-data/GUNW-003/file.tif",
          "preview_asset": "web-dashboard/layers/GUNW-003-band-1.png",
          "preview_crs": "EPSG:4326",
          "corners": [[0,0],[0,0],[0,0],[0,0]],
          "valid_pixels": 42,
          "display_scale": {"method": "track_group_robust_symmetric", "min": -1, "max": 1}
        }
      ],
      "source_sha256": "...",
      "validation_scope": "structural_and_provenance_not_independent_geophysical_validation"
    }
  ],
  "science_limitations": [
    "Pairwise LOS values are not automatically cumulative displacement.",
    "Independent geophysical validation has not been performed."
  ]
}
```

The example values above are placeholders illustrating the schema; they must never ship as a real product record.

## Rules

- `observations` are ordered deterministically by secondary date, then reference date, track and stable ID. Product IDs must not change across reruns of the same manifest.
- An observation is an acquisition pair, not a point sample of a continuous time series. Retain both acquisition dates.
- `corners` ordering is MapLibre image-source order: northwest, northeast, southeast, southwest, all in WGS84 longitude/latitude.
- Band names and units must be read from the raster; do not assume all product families share a band schema.
- If a band unit is missing, label it “source units not declared” instead of guessing.
- `valid_pixels` count is recomputed from the same output band/NoData policy used by the source validator and reconciled to the product record.
- `display_scale` is fixed within the comparison group used for playback; its method and numerical limits appear in the legend and export metadata.
- `visual_assets_status` cannot overwrite or promote scientific validation. The latter remains `NOT_PERFORMED` unless independently validated by an approved method.
- Asset paths are relative, normalized, never absolute, and must reject traversal segments (`..`).
- A STAC Item's `datetime` must be stated carefully: use secondary acquisition for sortable display time and retain reference/secondary dates separately. Include geometry and projection/raster metadata when available.
