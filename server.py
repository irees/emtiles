"""EMTiles-aware MBTiles Server."""
import os
import json
import twisted.python.failure
import twisted.internet
import twisted.web.resource
import twisted.web.server
import emtiles.tiles

VIEW = """
<!DOCTYPE html>
<html>
<head>
	<title>EMTiles Demo</title>
    <link rel="stylesheet" href="http://leafletjs.com/dist/leaflet.css" />
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="//ajax.googleapis.com/ajax/libs/jquery/1.11.0/jquery.min.js"></script>
    <script type="text/javascript">
        var maptemplate = 'tile/{z}/{x}/{y}';
        $(document).ready(function() {
            var update = function(){
                var index = $("#set-index").val();
                var nz = $("#set-nz").val();
                layer.setUrl(maptemplate+"?index="+index+"&nz="+nz);
            }
            $("#set-index").change(update);
            $("#set-nz").change(update);
        });
    </script>
</head>
<body>
    <div>
        Index: <input id="set-index" type="range" min="0" max="10" value="0">
        Z: <input id="set-nz" type="range" min="0" max="10" value="0">
    </div>
	<div id="map" style="width: 800px; height: 800px"></div>
	<script src="http://leafletjs.com/dist/leaflet.js"></script>
	<script>
		var map = L.map('map').setView([0, 0], 0);
        var layer = L.tileLayer(maptemplate, {
            'noWrap': true,
        });
        layer.addTo(map);
	</script>
</body>
</html>
"""

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
        db = request.postpath[0]
        method = request.postpath[1]
        if method == 'tile':
            method = self.tile
        elif method == 'info':
            method = self.info
        else:
            method = self.view
        return method(request)
    
    def view(self, request):
        return VIEW, {}
    
    def tile(self, request):
        assert len(request.postpath) == 5
        db = request.postpath[0]
        db = "%s.mbtiles"%os.path.basename(db)
        if not os.path.exists(db):
            raise HTTP404("Tileset not found.")
        index = 0
        if request.args.get('index'):
            index = int(request.args['index'][0])
        nz = 0
        if request.args.get('nz'):
            nz = int(request.args['nz'][0])
        level = int(request.postpath[2])
        x = int(request.postpath[3])
        # Y is flipped in MBTiles!
        y = int(request.postpath[4])
        y = 2**level - 1 - y
        tiles = emtiles.tiles.EMTile(db)
        try:
            data = tiles.read_tilestack(index=index, nz=nz, level=level, x=x, y=y)
        except:
            raise HTTP404("Tile not found.")
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
    
