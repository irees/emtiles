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

# Test image from Ryan Rochat.

class EMTile(object):
    def __init__(self, db, tileformat='jpg'):
        self.db = db
        self.conn = None
        self.tileformat = tileformat
        self.open()

    def open(self):
        self.conn = sqlite3.connect(self.db)

    def close(self):
        self.conn.close()
        
    def commit(self):
        self.conn.commit()
        
    def abort(self):
        self.conn.abort()
        
    def create(self):
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
                    tilestack.tile_nz = 0
        """
        metadata = {
            'name': self.db,
            'type': 'baselayer',
            'version': '1.1',
            'description': 'EM Tiles',
            'format': self.tileformat
        }
        cursor = self.conn.cursor()
        cursor.execute(create_tilestack)
        cursor.execute(create_tileinfo)
        cursor.execute(create_metadata)
        cursor.execute(create_tiles)
        for k,v in metadata.items():
            cursor.execute("""INSERT INTO metadata(name, value) VALUES (?, ?)""", [k, v])
        cursor.close()        
        
    def insert_tile(self, fsp, index, nz, level, x, y, unlink=False):
        print "fsp: %s, zoom_level: %s, tile_column: %s, tile_row: %s"%(fsp, level, x, y)
        with open(fsp) as f:
            data = f.read()
        cursor = self.conn.cursor()
        query = """INSERT INTO tilestack(tile_index, tile_nz, zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?, ?, ?);"""
        cursor.execute(query, [index, nz, level, x, y, sqlite3.Binary(data)])
        cursor.close()
        if unlink:
            os.unlink(fsp)

    def insert_tileinfo(self, fsp, index, nz, info_type, info_resolution, unlink=False):
        with open(fsp) as f:
            data = f.read()
        cursor = self.conn.cursor()
        query = """INSERT INTO tileinfo(tile_index, tile_nz, info_type, info_resolution, info_data) VALUES (?, ?, ?, ?, ?);"""
        cursor.execute(query, [index, nz, info_type, info_resolution, sqlite3.Binary(data)])
        cursor.close()
        if unlink:
            os.unlink(fsp)
        
    def read_tilestack(self, index, nz, level, x, y):
        query = """SELECT tile_data FROM tilestack WHERE tile_index = ? AND tile_nz = ? AND zoom_level = ? and tile_column = ? and tile_row = ?;"""
        cursor = self.conn.cursor()
        cursor.execute(query, [index, nz, level, x, y])
        data = cursor.fetchone()[0]
        cursor.close()
        return data

    def read_tile(self, level, x, y, **kwargs):
        query = """SELECT tile_data FROM tiles WHERE zoom_level = ? and tile_column = ? and tile_row = ?;"""
        cursor = self.conn.cursor()
        cursor.execute(query, [level, x, y])
        data = cursor.fetchone()[0]
        cursor.close()
        return data        
        
    def read_tileinfo(self, index, nz, info_type, info_resolution):
        query = """SELECT info_data FROM tileinfo WHERE tile_index = ? AND tile_nz = ? AND info_type = ? and info_resolution = ?;"""
        cursor = self.conn.cursor()
        cursor.execute(query, [index, nz, info_type, info_resolution])
        data = cursor.fetchone()[0]
        cursor.close()
        return data
