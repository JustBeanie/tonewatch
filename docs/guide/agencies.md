# Agencies

An agency identifies who a tone set alerts. Configure agencies through the authenticated `/api/agencies` CRUD endpoints and link one from a tone set with `agency_id`.

Each agency has a slug `id`, `name`, `short_name`, `kind` (`fire`, `ems`, `police`, `rescue`, `dispatch`, or `other`), `color`, `description`, address, WGS84 `location`, optional stations, phone, HTTP(S) website, radio notes, tags, notes, and up to 20 unique case-insensitive `cad_names`.

Coverage is optional GeoJSON `Polygon` or `MultiPolygon`. Coordinates use RFC 7946 order `[longitude, latitude]`; rings have at least four positions and repeat their first position at the end:

```json
{"type":"Polygon","coordinates":[[[-105.1,40.1],[-105.0,40.1],[-105.0,40.2],[-105.1,40.1]]]}
```

Coverage is limited to 10,000 vertices and 256 KiB serialized. The GeoJSON endpoint returns agency locations, station points, and coverage features.

Map tiles are off by default. An empty `map.tile_url` makes no external map requests. Enabling a tile template sends the viewer IP address and requested map area to that provider, so configure only a provider you trust. The OpenStreetMap preset is explicit opt-in and includes required attribution.
