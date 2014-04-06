# Electron Microscopy MBTiles

** EXPERIMENTAL **

We have been creating tilesets for in-browser previews of EM images for many
years. Users appreciate the previews because these files are frequently quite
large, and are often in uncommon or proprietary formats. Our tile container is
a simple JSON header, followed by concatenated JPG and PNG files that are
referenced by offsets. This package is an experiment in using the MBTiles
container format as an alternative.

Because EM images are frequently stacks of 2D images or 3D images the database
contains an additional table to support multiple tilesets. Tiles are stored in
the "tilestack" table, similar to MBTiles "tiles" but with additional
"tile_index" and "tile_nz" columns. For compatibility, the "tiles" table is a
view where tile_index = 0 and tile_nz = 1 (e.g. simple 2D image). This allows
an EM aware tile server to serve multiple tilesets, while still allowing
standard MBTile software to work with basic 2D images.
