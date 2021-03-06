import math
import os
import json
import tempfile
import argparse

import EMAN2
import emtiles.tiles

class EMDataBuilder(object):
    """Create an MBTiles SQLite database from an EMAN2-readable image.
    
    Examples:
    builder = EMDataBuilder("test.dm3", "test.dm3.mbtiles")
    builder.build()
    """
    def __init__(self, infile, outfile, tileformat='jpg', unlink=False):
        """Input image, output MBTiles."""
        self.infile = infile
        self.writer = emtiles.tiles.EMTile(outfile, tileformat=tileformat)
        self.tileformat = tileformat
        self.unlink = unlink
        self.tmpdir = '.' # tempfile.mkdtemp(prefix='emtiles.')

    def log(self, msg):
        print msg
    
    def build(self):
        """Build!"""
        self.log("Building: %s"%(self.infile))
        self.writer.create()
        # EM files often contain stacks of images. Build for each image.
        self.nimg = EMAN2.EMUtil.get_image_count(self.infile)
        for index in range(self.nimg):
            self.build_image(index)
        self.writer.commit()

    def build_image(self, index):
        """Build for an image index in the file."""
        self.log("build_image: %s"%index)
        img = EMAN2.EMData()
        img.read_image(self.infile, index, True)
        header = img.get_attr_dict()
        if header['nz'] == 1:
            # 2D Image
            img2 = EMAN2.EMData()
            img2.read_image(self.infile, index, False)
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
                img2.read_image(self.infile, 0, False, region)
                self.build_nz(img2, index=index, nz=i)
        return header

    def build_nz(self, img, nz=0, index=0):
        """Build tiles, thumbnails, pspec, etc. for a 2D EMData."""
        for tile in self.build_tiles(img, nz=nz, index=index):
            self.writer.insert_tile(*tile, unlink=self.unlink)

        for info in self.build_pspec(img, nz=nz, index=index):
            self.writer.insert_tileinfo(*info, unlink=self.unlink)

        for info in self.build_fixed(img, nz=nz, index=index):
            self.writer.insert_tileinfo(*info, unlink=self.unlink)
                    
    def build_tiles(self, img, index=0, nz=0, tilesize=256):
        """Build tiles for a 2D EMData."""
        self.log("build_tiles: nz %s, index %s, tilesize: %s"%(nz, index, tilesize))
        # Work with a copy of the EMData
        img2 = img.copy()        
        # Calculate the number of zoom levels based on the tile size
        levels = math.ceil( math.log( max(img.get_xsize(), img.get_ysize()) / float(tilesize), 2.0 )  )
        # Tile header
        header = img.get_attr_dict()
        # Step through shrink range creating tiles
        for level in range(int(levels), -1, -1):
            self.log("... level: %s"%level)
            rmin = img2.get_attr("mean") - img2.get_attr("sigma") * 3.0
            rmax = img2.get_attr("mean") + img2.get_attr("sigma") * 3.0
            # Center the image
            nx = img2.get_xsize()
            ny = img2.get_ysize()
            nxoffset = (tilesize * 2**level - nx) / 2.0
            nyoffset = (tilesize * 2**level - ny) / 2.0
            print "nxoffset?:", nxoffset
            print "nyoffset?:", nyoffset
            for x in range(0, tilesize*2**level, tilesize):
                for y in range(0, tilesize*2**level, tilesize):
                    # Write output
                    i = img2.get_clip(EMAN2.Region(x-nxoffset, y-nyoffset, tilesize, tilesize), fill=rmax)
                    i.set_attr("render_min", rmin)
                    i.set_attr("render_max", rmax)
                    fsp = "tile.index-%d.nz-%d.level-%d.x-%d.y-%d.%s"%(index, nz, level, x/tilesize, y/tilesize, self.tileformat)
                    fsp = os.path.join(self.tmpdir, fsp)
                    i.write_image(fsp)
                    # Insert into MBTiles
                    yield (fsp, index, nz, level, x/tilesize, y/tilesize)
            # Shrink by 2 for next round.
            img2.process_inplace("math.meanshrink",{"n":2})
    
    def build_fixed(self, img, index=0, nz=0, tilesize=256):
        """Build thumbnail of a 2D EMData."""
        # Output files
        fsp = "fixed.index-%d.nz-%d.size-%d.png"%(index, nz, tilesize)
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
            
    def build_pspec(self, img, tilesize=512, nz=0, index=0):
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
        
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("infile", help="Input EM file")
    parser.add_argument("outfile", help="Output MBTiles file")
    parser.add_argument("--tileformat", help="Tile format", default="jpg")
    parser.add_argument("--keep", help="Don't remove temporary tile files", action='store_true')
    args = parser.parse_args()
    builder = EMDataBuilder(args.infile, args.outfile, tileformat=args.tileformat, unlink=(not args.keep))
    builder.build()
    