const fs = require("fs");
const topojson = require("topojson-client");
const world = require("world-atlas/land-110m.json");

const geo = topojson.feature(world, world.objects.land);

// Ray-casting point-in-polygon (supports MultiPolygon / Polygon)
function pointInRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    const intersect = (yi > y) !== (yj > y) &&
      x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function pointInPolygon(x, y, polygon) {
  // polygon = array of rings, first is exterior, rest are holes
  if (!pointInRing(x, y, polygon[0])) return false;
  for (let k = 1; k < polygon.length; k++) {
    if (pointInRing(x, y, polygon[k])) return false;
  }
  return true;
}

function isLand(lon, lat) {
  for (const feature of geo.features) {
    const geom = feature.geometry;
    if (geom.type === "Polygon") {
      if (pointInPolygon(lon, lat, geom.coordinates)) return true;
    } else if (geom.type === "MultiPolygon") {
      for (const poly of geom.coordinates) {
        if (pointInPolygon(lon, lat, poly)) return true;
      }
    }
  }
  return false;
}

const GRID_W = 220; // longitude samples across -180..180
const GRID_H = 110; // latitude samples across 85..-85
const dots = [];

for (let j = 0; j < GRID_H; j++) {
  const lat = 85 - (j / (GRID_H - 1)) * 170;
  for (let i = 0; i < GRID_W; i++) {
    const lon = -180 + (i / (GRID_W - 1)) * 360;
    if (isLand(lon, lat)) {
      // normalized 0..1 x/y for easy canvas scaling
      dots.push([
        Math.round(((lon + 180) / 360) * 1000) / 1000,
        Math.round(((85 - lat) / 170) * 1000) / 1000,
      ]);
    }
  }
}

fs.writeFileSync(
  "../static/js/world-dots.json",
  JSON.stringify(dots)
);
console.log("Generated", dots.length, "land dots");
