# Electron Microscopy MBTiles

** EXPERIMENTAL **

We have been creating tilesets for in-browser previews of EM images for many
years. Users appreciate these previews because these files are frequently quite
large, and are often in uncommon or proprietary formats. Our tile container is
a simple JSON header, followed by concatenated JPG and PNG files that are
referenced by offsets. This package is an experiment in using the MBTiles
format as an alternative container.

Because EM images are frequently stacks of 2D images or 3D volumes, the
database contains an additional table to support multiple tilesets. Tiles are
stored in the "tilestack" table, similar to MBTiles "tiles" but with additional
"tile_index" and "tile_nz" columns. For compatibility, the "tiles" table is a
view where tile_index = 0 and tile_nz = 0 (e.g. simple 2D image). This allows
an EM aware tile server to serve tilesets of image stacks and 3D volumes, while
still allowing standard MBTile software to view basic 2D images.
