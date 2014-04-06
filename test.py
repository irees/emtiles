import tiles
import sqlite3

TEST_INFILE = "images/B-capsid-2075.tif"
TEST_MBTILES = "test.mbtiles"

if __name__ == "__main__":
    # builder = tiles.EMDataBuilder(TEST_INFILE, TEST_MBTILES)
    # builder.build()
    db = sqlite3.connect(TEST_MBTILES)
    cursor = db.cursor()
    
    # Make sure we have all the tiles!
    for i in [0, 1,2,3,4]:
        cursor.execute("""SELECT * FROM tiles WHERE zoom_level = ?;""", [i])
        rows = cursor.fetchall()
        print "Expect %s tiles, found %s"%(len(rows), 2**(2*i))
        assert len(rows) == 2**(2*i)

    # Check for tile info (pspec, json, thumbnail)
    cursor.execute("""SELECT * FROM tileinfo;""")
    for row in cursor.fetchall():
        print "Found info: tile_index %s, tile_nz %s, info_type %s, info_resolution %s"%(row[0], row[1], row[2], row[3])

    # TODO: Test for image stacks
    # TODO: Test for 3D images.

    db.close()