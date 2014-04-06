# Electron Microscopy MBTiles

We have been creating zoomable tilesets from EM images for many years, stored
in a custom tile container comprised of a JSON header and concatenated JPG and
PNG files that are referenced by file offset. This package instead uses the
popular MBTiles container format for storing the tilesets.

Because EM images are frequently stacks of 2D images, or 3D images, the MBTiles
spec has been slightly extended to support multiple tilesets. These are stored
in the "tilestack" table, similar to MBTiles "tiles" but with additional
"index" and "nz" columns. For compatibility, the "tiles" table is a view where
index = 0 and nz = 1. This allows an EM aware tile server to serve multiple
tilesets, while still allowing standard MBTile software to work with basic 2D
images.
