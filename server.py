"""EMTiles-aware MBTiles Server."""
import os
import json
import twisted.python.failure
import twisted.internet
import twisted.web.resource
import twisted.web.server
import emtiles.tiles

class HTTPResponseCode(Exception):
    code = None

class HTTP404(Exception):
    code = 404

class EMTileServer(twisted.web.resource.Resource):
    """EMTileServer."""
    isLeaf = True
    def render_GET(self, request):
        d = twisted.internet.threads.deferToThread(self._render, request)
        d.addCallback(self._render_cb, request)
        d.addErrback(self._render_eb, request)
        return twisted.web.server.NOT_DONE_YET
        
    def _render_cb(self, result, request):
        # Result is (data, headers).
        data, headers = result
        for k,v in headers.items():
            request.setHeader(k, v)
        request.write(data)
        request.finish()
    
    def _render_eb(self, failure, request):
        try:
            # Raise the failure exception
            if isinstance(failure, twisted.python.failure.Failure):
                failure.raiseException()
            else:
                raise failure
        except (twisted.internet.defer.CancelledError), e:
            # Closed connection error. Nothing to write, 
            # and no connection to close.
            return
        except HTTPResponseCode, e:
            # HTTP errors
            data = "HTTP error: %s"%e
        except Exception, e:
            # General error
            data = "General error: %s"%e
        # Write the response
        headers = {}
        request.setResponseCode(getattr(e, 'code', 500))
        [request.setHeader(k, v) for k,v in headers.items()]
        request.write(data)
        request.finish()
        
    def _render(self, request):
        # Route the request.
        method = request.postpath[1]
        if method == 'tile':
            method = self.tile
        elif method == 'info':
            method = self.info
        else:
            raise HTTP404("Unknown method.")
        return method(request)
    
    def tile(self, request):
        assert len(request.postpath) == 5
        db = request.postpath[0]
        db = "%s.mbtiles"%os.path.basename(db)
        index = 0
        nz = 1
        level = int(request.postpath[2])
        x = int(request.postpath[3])
        # Y is flipped in MBTiles!
        y = int(request.postpath[4])
        y = 2**level - 1 - y
        tiles = emtiles.tiles.EMTile(db)
        #try:
        data = tiles.read_tile(index=0, nz=1, level=level, x=x, y=y)
        #except:
        #    raise HTTP404("Tile not found.")
        return str(data), {'Content-Type': 'image/jpg'}

    def info(self, request):
        return "tile info", {}

def start():
    tileserver = EMTileServer()
    site = twisted.web.server.Site(tileserver)
    twisted.internet.reactor.listenTCP(8080, site)
    twisted.internet.reactor.run()
    
if __name__ == "__main__":
    start()
    
