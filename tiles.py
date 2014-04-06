"""File handlers."""
import math
import os
import json
import sys
import tempfile
import cPickle as pickle

import sqlite3
import EMAN2

class EMDataBuilder(object):
    """Convert EM Images to MBTiles.
    
    Examples:
    builder = EMDataBuilder()
    tile = builder.build("test.dm3", "test.dm3.mbtiles")
    """
    def log(self, msg):
        print msg
    
    def build(self, workfile, outfile):
        """Main build function."""
        self.log("Building: %s -> %s"%(workfile, outfile))
        self.workfile = workfile
        self.tmpdir = "build" # tempfile.mkdtemp(prefix='emen2thumbs.')

        # Open and create the sqlite database
        self.conn = sqlite3.connect(outfile)
        self.create_sqlite()
        
        # EM files often contain stacks of images. Build for each image.
        self.nimg = EMAN2.EMUtil.get_image_count(workfile)
        for index in range(self.nimg):
            self.build_image(index)
        
        self.conn.commit()
        self.conn.close()

    def build_image(self, index):
        """Build a single image index in the file."""
        # Copy basic header information
        self.log("build_image: %s"%index)
        header = {}
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
                self.build_nz(img2, index=index, fixed=[256,512])
            else:
                # regular old 2D image -- also generate power spectrum + tiles.
                self.build_nz(img2, index=index, tile=True, pspec=True, fixed=[256,512])
        else:        
            # 3D Image -- read region for each Z slice
            for i in range(header['nz']):
                region = EMAN2.Region(0, 0, i, header['nx'], header['ny'], 1)
                img2 = EMAN2.EMData()
                img2.read_image(self.workfile, 0, False, region)
                self.build_nz(img2, index=index, nz=i, fixed=[256,512])
        return header

    def build_nz(self, img, nz=1, index=0, tile=False, pspec=False, fixed=None):
        """Build a single 2D slice from a 2D or 3D image."""
        self.log("build_nz: nz %s, index %s"%(nz, index))
        header = {}
        h = img.get_attr_dict()
        header['nx'] = h['nx']
        header['ny'] = h['ny']
        header['nz'] = h['nz']
        if tile:
            header['tiles'] = self.build_tiles(img, nz=nz, index=index)

        if pspec:
            header['pspec'], header['pspec1d'] = self.build_pspec(img, nz=nz, index=index)

        if fixed:
            header['fixed'] = {}
            for f in fixed:
                header['fixed'][f] = self.build_fixed(img, tilesize=f, nz=nz, index=index)

        return header
            
    def build_tiles(self, img, index=0, nz=1, tilesize=256):
        """Build tiles for a 2D slice."""
        self.log("build_tiles: nz %s, index %s, tilesize: %s"%(nz, index, tilesize))
        # Work with a copy of the EMData
        img2 = img.copy()        
        # Calculate the number of zoom levels based on the tile size
        levels = math.ceil( math.log( max(img.get_xsize(), img.get_ysize()) / tilesize) / math.log(2.0) )
        # Tile header
        header = img.get_attr_dict()
        tile_dict = {}

        # Step through shrink range creating tiles
        for level in range(1, int(levels)+1):
            self.log("... level: %s"%level)
            scale = 2**level
            rmin = img2.get_attr("mean") - img2.get_attr("sigma") * 3.0
            rmax = img2.get_attr("mean") + img2.get_attr("sigma") * 3.0
            for x in range(0, img2.get_xsize(), tilesize):
                for y in range(0, img2.get_ysize(), tilesize):
                    i = img2.get_clip(EMAN2.Region(x, y, tilesize, tilesize), fill=rmax)
                    i.set_attr("render_min", rmin)
                    i.set_attr("render_max", rmax)
                    i.set_attr("jpeg_quality", 80)
                    # Write output
                    fsp = "tile.index-%d.scale-%d.z-%d.x-%d.y-%d.jpg"%(index, scale, nz, x/tilesize, y/tilesize)
                    fsp = os.path.join(self.tmpdir, fsp)
                    self.insert_tile(i, fsp, index, nz, level, x/tilesize, y/tilesize)
                    
            # Shrink by 2 for next round.
            img2.process_inplace("math.meanshrink",{"n":2})

        return tile_dict
    
    def insert_tile(self, img, fsp, index, nz, level, x, y):
        self.log("... write_img: fsp %s, index %s, nz %s, level %s, x %s, y %s"%(fsp, index, nz, level, x, y))
        img.write_image(fsp)
        with open(fsp) as f:
            data = f.read()
        os.unlink(fsp)
        cursor = self.conn.cursor()
        query = """
            INSERT INTO tilestack(
                tile_index, 
                tile_nz, 
                zoom_level, 
                tile_column, 
                tile_row, 
                tile_data) 
            VALUES (?, ?, ?, ?, ?, ?);
        """
        cursor.execute(query, [index, nz, level, x, y, sqlite3.Binary(data)])

    def build_fixed(self, img, tilesize=256, nz=1, index=0):
        """Build a thumbnail of a 2D EMData."""
        # Output files
        fsp = "fixed.index-%d.z-%d.size-%d.jpg"%(index, nz, tilesize)
        fsp = os.path.join(self.tmpdir, fsp)

        # The scale factor
        thumb_scale = img.get_xsize() / float(tilesize), img.get_ysize() / float(tilesize)
        sc = 1 / max(thumb_scale)

        if tilesize == 0 or sc >= 1.0:
            # Write out a full size jpg
            img2 = img.copy()
        else:
            # Shrink the image
            # print "shrink to thumbnail with scale factor:", sc, 1/sc, math.ceil(1/sc)
            # img2 = img.process("xform.scale", {"scale":sc, "clip":tilesize})
            img2 = img.process("math.meanshrink", {'n':math.ceil(1/sc)})

        # Adjust the brightness for rendering
        rmin = img2.get_attr("mean") - img2.get_attr("sigma") * 3.0
        rmax = img2.get_attr("mean") + img2.get_attr("sigma") * 3.0
        img2.set_attr("render_min", rmin)
        img2.set_attr("render_max", rmax)
        img2.set_attr("jpeg_quality", 80)        
        img2.write_image(fsp)
        
        # Awful hack to write out regular thumbs
        self.copyout = []
        if index == 0 and nz == 1 and tilesize in self.copyout:
            # print "...copy thumb:", tilesize, self.copyout[tilesize]
            img2.write_image(self.copyout[tilesize])
        return [fsp, None, 'jpg', img2.get_xsize(), img2.get_ysize()]
            
    def build_pspec(self, img, tilesize=512, nz=1, index=0):
        """Build a 2D FFT and 1D rotationally averaged power spectrum of a 2D EMData."""
        
        # Return dictionaries
        pspec_dict = {}
        pspec1d_dict = {}

        # Output files
        outfile = "pspec.index-%d.z-%d.size-%d.png"%(index, nz, tilesize)
        outfile = os.path.join(self.tmpdir, outfile)        

        outfile1d = "pspec1d.index-%d.z-%d.size-%d.json"%(index, nz, tilesize)
        outfile1d = os.path.join(self.tmpdir, outfile1d)        

        # Create a new image to hold the 2D FFT
        nx, ny = img.get_xsize() / tilesize, img.get_ysize() / tilesize
        a = EMAN2.EMData()
        a.set_size(tilesize, tilesize)
        
        # Image isn't big enough..
        if (ny<2 or nx<2):
            return pspec_dict, pspec1d_dict
            
        # Create FFT
        for y in range(1,ny-1):
            for x in range(1,nx-1):
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
        a.write_image(outfile)

        # Add to dictionary
        pspec_dict[tilesize] = [outfile, None, 'png', a.get_xsize(), a.get_ysize()]

        # Calculate
        t = (tilesize/2)-1
        y = a.calc_radial_dist(t, 1, 1, 0) # radial power spectrum (log)
        f = open(outfile1d, "w")
        json.dump(y,f)
        f.close()
        pspec1d_dict[tilesize] = [outfile1d, None, 'json', t]
        
        # Return both the 2D and 1D files
        return pspec_dict, pspec1d_dict

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
                tile_z integer,
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

        # The metadata table is used as a key/value store for settings. Five keys are required:
        # name: The plain-english name of the tileset.
        # type: overlay or baselayer
        # version: The version of the tileset, as a plain number.
        # description: A description of the layer as plain text.
        # format: The image file format of the tile data: png or jpg
        cursor = self.conn.cursor()
        cursor.execute(create_tilestack)
        cursor.execute(create_tileinfo)
        cursor.execute(create_metadata)
        cursor.execute(create_tiles)
        
        metadata = {
            'name': 'test',
            'type': 'baselayer',
            'version': '1.1',
            'description': 'test',
            'format': 'jpg'
        }
        for k,v in metadata.items():
            cursor.execute("""INSERT INTO metadata(name, value) VALUES (?, ?)""", [k, v])
        cursor.close()        


# IMPORTANT -- Do not change this.
if __name__ == "__main__":
    builder = EMDataBuilder()
    tile = builder.build("test.dm3", "test.mbtiles")            
    
            
            