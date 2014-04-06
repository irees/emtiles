"""Create MBTiles from an EMAN2-readable image.

Single 2D images, stacks of images, and 3D images are supported.

See README.md for additional details. Note: experimental!
"""
import math
import os
import json
import sys
import tempfile
import argparse

import sqlite3
import EMAN2

# Test image from Ryan Rochat.

class EMDataBuilder(object):
    """Convert MBTiles from an EMAN2-readable image.
    
    Examples:
    builder = EMDataBuilder("test.dm3", "test.dm3.mbtiles")
    builder.build()
    """
    
    def __init__(self, workfile, outfile):
        self.workfile = workfile
        self.outfile = outfile
        self.tmpdir = 'build' # tempfile.mkdtemp(prefix='emtiles.')

    def log(self, msg):
        print msg
    
    def build(self):
        """Build a tileset for this file."""
        self.log("Building: %s -> %s"%(self.workfile, self.outfile))

        # Open and create the sqlite database
        self.conn = sqlite3.connect(self.outfile)
        self.create_sqlite()
        
        # EM files often contain stacks of images. Build for each image.
        self.nimg = EMAN2.EMUtil.get_image_count(self.workfile)
        for index in range(self.nimg):
            self.build_image(index)
        
        self.conn.commit()
        self.conn.close()

    def build_image(self, index):
        """Build a single image index in the file."""
        self.log("build_image: %s"%index)
        img = EMAN2.EMData()
        img.read_image(self.workfile, index, True)
        header = img.get_attr_dict()
        if header['nz'] == 1:
            # 2D Image
            img2 = EMAN2.EMData()
            img2.read_image(self.workfile, index, False)
            img2.process_inplace("normalize")
            if self.nimg > 1:
                # ... stack of 2D images.
                self.build_nz(img2, index=index)
            elif self.nimg == 1:
                # regular old 2D image -- also generate power spectrum + tiles.
                self.build_nz(img2, index=index)
        else:        
            # 3D Image -- read region for each Z slice
            for i in range(header['nz']):
                region = EMAN2.Region(0, 0, i, header['nx'], header['ny'], 1)
                img2 = EMAN2.EMData()
                img2.read_image(self.workfile, 0, False, region)
                self.build_nz(img2, index=index, nz=i)
        return header

    def build_nz(self, img, nz=1, index=0):
        """Build a single 2D slice from a 2D or 3D image."""
        for tile in self.build_tiles(img, nz=nz, index=index):
            self._insert_tile(*tile)

        for info in self.build_pspec(img, nz=nz, index=index):
            self._insert_tileinfo(*info)

        for info in self.build_fixed(img, nz=nz, index=index):
            self._insert_tileinfo(*info)
                    
    def build_tiles(self, img, index=0, nz=1, tilesize=256):
        """Build tiles for a 2D slice."""
        self.log("build_tiles: nz %s, index %s, tilesize: %s"%(nz, index, tilesize))
        # Work with a copy of the EMData
        img2 = img.copy()        
        # Calculate the number of zoom levels based on the tile size
        levels = math.ceil( math.log( max(img.get_xsize(), img.get_ysize()) / tilesize) / math.log(2.0) )
        # Tile header
        header = img.get_attr_dict()
        # Step through shrink range creating tiles
        for level in range(int(levels), -1, -1):
            self.log("... level: %s"%level)
            rmin = img2.get_attr("mean") - img2.get_attr("sigma") * 3.0
            rmax = img2.get_attr("mean") + img2.get_attr("sigma") * 3.0
            for x in range(0, img2.get_xsize(), tilesize):
                for y in range(0, img2.get_ysize(), tilesize):
                    # Write output
                    i = img2.get_clip(EMAN2.Region(x, y, tilesize, tilesize), fill=rmax)
                    i.set_attr("render_min", rmin)
                    i.set_attr("render_max", rmax)
                    fsp = "tile.index-%d.level-%d.z-%d.x-%d.y-%d.jpg"%(index, level, nz, x/tilesize, y/tilesize)
                    fsp = os.path.join(self.tmpdir, fsp)
                    i.write_image(fsp)
                    # Insert into MBTiles
                    yield (fsp, index, nz, level, x/tilesize, y/tilesize)
            # Shrink by 2 for next round.
            img2.process_inplace("math.meanshrink",{"n":2})
    
    def build_fixed(self, img, index=0, nz=1, tilesize=256):
        """Build a thumbnail of a 2D EMData."""
        # Output files
        fsp = "fixed.index-%d.z-%d.size-%d.png"%(index, nz, tilesize)
        fsp = os.path.join(self.tmpdir, fsp)

        # The scale factor
        thumb_scale = img.get_xsize() / float(tilesize), img.get_ysize() / float(tilesize)
        sc = 1 / max(thumb_scale)
        if tilesize == 0 or sc >= 1.0:
            # Tiny image, use full size.
            img2 = img.copy()
        else:
            # Shrink the image
            img2 = img.process("math.meanshrink", {'n':math.ceil(1/sc)})

        # Adjust the brightness for rendering
        rmin = img2.get_attr("mean") - img2.get_attr("sigma") * 3.0
        rmax = img2.get_attr("mean") + img2.get_attr("sigma") * 3.0
        img2.set_attr("render_min", rmin)
        img2.set_attr("render_max", rmax)
        img2.set_attr("jpeg_quality", 80)        
        img2.write_image(fsp)
        yield fsp, index, nz, 'thumbnail', tilesize
            
    def build_pspec(self, img, tilesize=512, nz=1, index=0):
        """Build a 2D FFT and 1D rotationally averaged power spectrum of a 2D EMData."""
        # Output files
        outfile = "pspec.index-%d.z-%d.size-%d.png"%(index, nz, tilesize)
        outfile1d = "pspec1d.index-%d.z-%d.size-%d.json"%(index, nz, tilesize)

        # Create a new image to hold the 2D FFT
        nx, ny = img.get_xsize() / tilesize, img.get_ysize() / tilesize
        a = EMAN2.EMData()
        a.set_size(tilesize, tilesize)
        
        # Create FFT
        for y in range(1, ny-1):
            for x in range(1, nx-1):
                c = img.get_clip(EMAN2.Region(x*tilesize, y*tilesize, tilesize, tilesize))
                c.process_inplace("normalize")
                c.process_inplace("math.realtofft")
                c.process_inplace("math.squared")
                a += c

        # Reset the center value
        a.set_value_at(tilesize/2, tilesize/2, 0, .01)

        # Adjust brightness
        a -= a.get_attr("minimum") - a.get_attr("sigma") * .01
        a.process_inplace("math.log")
        a.set_attr("render_min", a.get_attr("minimum") - a.get_attr("sigma") * .1)
        a.set_attr("render_max", a.get_attr("mean") + a.get_attr("sigma") * 4.0)

        # Write out the PSpec png
        fsp = os.path.join(self.tmpdir, outfile)
        a.write_image(fsp)
        yield fsp, index, nz, 'pspec', 512

        # Calculate radial power spectrum
        t = (tilesize/2)-1
        y = a.calc_radial_dist(t, 1, 1, 0) 
        # Next version, I'll just insert data directly into MBTiles,
        # without going to disk and back.
        fsp = os.path.join(self.tmpdir, outfile1d)
        with open(fsp, 'wb') as f:
            json.dump(y, f)
        yield fsp, index, nz, 'pspec_json', tilesize/2    

    def create_sqlite(self):
        create_tilestack = """
            CREATE TABLE tilestack (
                tile_index integer,
                tile_nz integer,
                zoom_level integer, 
                tile_column integer, 
                tile_row integer, 
                tile_data blob
            );
            """
        create_tileinfo = """
            CREATE TABLE tileinfo (
                tile_index integer,
                tile_nz integer,
                info_type text,
                info_resolution integer,
                info_data blob
            );"""
        create_metadata = """
            CREATE TABLE metadata (name text, value text);
            """
        create_tiles = """
            CREATE VIEW tiles AS
                SELECT 
                    tilestack.zoom_level, 
                    tilestack.tile_column,
                    tilestack.tile_row,
                    tilestack.tile_data
                FROM tilestack
                WHERE 
                    tilestack.tile_index = 0 AND
                    tilestack.tile_nz = 1                   
        """
        metadata = {
            'name': self.workfile,
            'type': 'baselayer',
            'version': '1.1',
            'description': 'EM Tiles',
            'format': 'jpg'
        }
        cursor = self.conn.cursor()
        cursor.execute(create_tilestack)
        cursor.execute(create_tileinfo)
        cursor.execute(create_metadata)
        cursor.execute(create_tiles)
        for k,v in metadata.items():
            cursor.execute("""INSERT INTO metadata(name, value) VALUES (?, ?)""", [k, v])
        cursor.close()        
        
    def _insert_tile(self, fsp, index, nz, level, x, y):
        with open(fsp) as f:
            data = f.read()
        cursor = self.conn.cursor()
        query = """INSERT INTO tilestack(tile_index, tile_nz, zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?, ?, ?);"""
        cursor.execute(query, [index, nz, level, x, y, sqlite3.Binary(data)])

    def _insert_tileinfo(self, fsp, index, nz, info_type, info_resolution):
        with open(fsp) as f:
            data = f.read()
        cursor = self.conn.cursor()
        query = """INSERT INTO tileinfo(tile_index, tile_nz, info_type, info_resolution, info_data) VALUES (?, ?, ?, ?, ?);"""
        cursor.execute(query, [index, nz, info_type, info_resolution, sqlite3.Binary(data)])

        
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("infile", help="Input EM file")
    parser.add_argument("outfile", help="Output MBTiles file")
    args = parser.parse_args()
    
    builder = EMDataBuilder(args.infile, args.outfile)
    builder.build()            
    
            
            