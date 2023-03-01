
from typing import Any, List, Optional, Tuple, Union
import arcpy
from arcpy._mp import ArcGISProject, Map, Layer as arcLayer
from arcpy.management import CreateTable

import os.path

from specklepy.api.credentials import Account, get_local_accounts
from specklepy.api.client import SpeckleClient
from specklepy.logging.exceptions import (
    GraphQLException,
    SpeckleException,
)
from specklepy.api.wrapper import StreamWrapper 
from specklepy.api.models import Branch, Stream, Streams
from osgeo import osr


try: 
    from speckle.ui.validation import tryGetStream
    from speckle.speckle_arcgis import SpeckleGIS
    from speckle.converter.layers import getAllProjLayers
except: 
    from speckle_toolbox.esri.toolboxes.speckle.ui.validation import tryGetStream
    from speckle_toolbox.esri.toolboxes.speckle.speckle_arcgis import SpeckleGIS
    from speckle_toolbox.esri.toolboxes.speckle.converter.layers import getAllProjLayers

def get_project_streams(self: SpeckleGIS, content: str = None):
    print("get proj streams")
    
    print("GET proj streams")
    project = self.gis_project
    table = findOrCreateSpeckleTable(project)
    if table is None: return 

    rows = arcpy.da.SearchCursor(table, "project_streams") 
    saved_streams = ""
    for x in rows:
        saved_streams: str = x[0]
        break
    temp = []
    ######### need to check whether saved streams are available (account reachable)
    if saved_streams != "":
        for url in saved_streams.split(","):
            try:
                sw = StreamWrapper(url)
                try: 
                    stream = tryGetStream(sw)
                except SpeckleException as e:
                    arcpy.AddWarning(e.message)
                    stream = None
                #strId = stream.id # will cause exception if invalid
                temp.append((sw, stream))
            except SpeckleException as e:
                arcpy.AddWarning(e.message)
            #except GraphQLException as e:
            #    logger.logToUser(e.message, Qgis.Warning)
    self.current_streams = temp
    
def set_project_streams(self: SpeckleGIS):

    print("SET proj streams")
    project = self.gis_project
    table = findOrCreateSpeckleTable(project)
    if table is None: return 

    value = ",".join([stream[0].stream_url for stream in self.current_streams])
    with arcpy.da.UpdateCursor(table, ["project_streams"]) as cursor:
        for row in cursor: # just one row
            cursor.updateRow([value])
    del cursor 
  
def get_project_layer_selection(self: SpeckleGIS):

    print("GET project layer selection")
    project = self.gis_project
    table = findOrCreateSpeckleTable(project)
    if table is None: return 
    
    rows = arcpy.da.SearchCursor(table, "project_layer_selection") 
    saved_layers = ""
    for x in rows:
        saved_layers = x[0]
        break
    
    temp = []
    proj_layers = getAllProjLayers(project)
    ######### need to check whether saved streams are available (account reachable)
    if saved_layers != "":
        for layerPath in saved_layers.split(","):
            found = 0
            for layer in proj_layers:
                print(layer.dataSource)
                if layer.dataSource == layerPath:
                    temp.append((layer.name(), layer))
                    found += 1
                    break
            if found == 0: 
                arcpy.AddWarning(f'Saved layer not found: "{layerPath}"')
    self.current_layers = temp

def set_project_layer_selection(self: SpeckleGIS):
    print("SET project layer selection")
    project = self.gis_project
    value = ",".join([layer[1].dataSource for layer in self.current_layers]) 
    print(value)

    table = findOrCreateSpeckleTable(project)
    if table is not None:
        with arcpy.da.UpdateCursor(table, ["project_layer_selection"]) as cursor:
            for row in cursor: # just one row
                cursor.updateRow([value])
        del cursor 

def get_survey_point(self: SpeckleGIS, content = None):
    print("get survey point")
    project = self.gis_project
    table = findOrCreateSpeckleTable(project)
    if table is None: return 

    rows = arcpy.da.SearchCursor(table, "lat_lon") 
    points = ""
    for x in rows:
        points = x[0]
        break

    if points != "": 
        vals: List[str] = points.replace(" ","").split(";")[:2]
        self.lat, self.lon = [float(i) for i in vals]

    
def set_survey_point(self: SpeckleGIS):

    # from widget (2 strings) to local vars + update SR of the map
    print("SET survey point")
    
    project = self.gis_project
    vals =[ str(self.dockwidget.surveyPointLat.text()), str(self.dockwidget.surveyPointLon.text()) ]

    try: 
        self.lat, self.lon = [float(i.replace(" ","")) for i in vals]
        pt = str(self.lat) + ";" + str(self.lon) 

        table = findOrCreateSpeckleTable(project)
        if table is not None:
            with arcpy.da.UpdateCursor(table, ["lat_lon"]) as cursor:
                for row in cursor: # just one row
                    cursor.updateRow([pt])
            del cursor   
        
        setProjectReferenceSystem(self)
        return True

    except Exception as e:
        arcpy.AddWarning("Lat, Lon values invalid: " + str(e))
        return False 

def setProjectReferenceSystem(self: SpeckleGIS):
    
    # save to project; create SR
    newCrsString = "+proj=tmerc +ellps=WGS84 +datum=WGS84 +units=m +no_defs +lon_0=" + str(self.lon) + " lat_0=" + str(self.lat) + " +x_0=0 +y_0=0 +k_0=1"
    newCrs = osr.SpatialReference()
    newCrs.ImportFromProj4(newCrsString)
    newCrs.MorphToESRI() # converts the WKT to an ESRI-compatible format
    
    validate = True if len(newCrs.ExportToWkt())>10 else False

    if validate: 
        newProjSR = arcpy.SpatialReference()
        newProjSR.loadFromString(newCrs.ExportToWkt())

        #source = osr.SpatialReference() 
        #source.ImportFromWkt(self.project.activeMap.spatialReference.exportToString())
        #transform = osr.CoordinateTransformation(source, newCrs)

        self.gis_project.activeMap.spatialReference =  newProjSR
        arcpy.AddMessage("Custom project Spatial Reference successfully applied")
    else:
        arcpy.AddWarning("Custom Spatial Reference could not be created")

    return True

def findOrCreateSpeckleTable(project: ArcGISProject) -> Union[str, None]:
    path = project.filePath.replace("aprx","gdb") #"\\".join(project.filePath.split("\\")[:-1]) + "\\speckle_layers\\" #arcpy.env.workspace + "\\" #
    fields = ["project_streams","project_layer_selection", "lat_lon"]
    if 'speckle_gis' not in arcpy.ListTables():
        try: 
            table = CreateTable(path, "speckle_gis")
            arcpy.management.AddField(table, "project_streams", "TEXT")
            arcpy.management.AddField(table, "project_layer_selection", "TEXT")
            arcpy.management.AddField(table, "lat_lon", "TEXT")

            cursor = arcpy.da.InsertCursor(table, fields )
            cursor.insertRow(["",""])
            del cursor
         
        except Exception as e:
            arcpy.addWarning("Error creating a table: " + str(e))
            return None
    else: 
        print("table already exists")
        # make sure fileds exist 
        table = path + "\\speckle_gis" 
        findOrCreateTableField(table, fields[0])
        findOrCreateTableField(table, fields[1])
        findOrCreateTableField(table, fields[2])
        
        findOrCreateRow(table, fields)

    return table

def findOrCreateTableField(table: str, field: str):
    try: 
        with arcpy.da.UpdateCursor(table, [field]) as cursor:
            value = None
            for row in cursor:
                value = row # tuple(val,)
                if value[0] is None: cursor.updateRow("")
                break # look at the 1st row only 
        del cursor

        #if value is None: # if there are no rows 
        #    cursor = arcpy.da.InsertCursor(table, [field])
        #    cursor.insertRow([""]) 
        #    del cursor
    
    except: # if field doesn't exist
        arcpy.management.AddField(table, field, "TEXT")
        #cursor = arcpy.da.InsertCursor(table, [field] )
        #cursor.insertRow([""])
        del cursor

def findOrCreateRow(table:str, fields: List[str]):
    # check if the row exists 
    cursor = arcpy.da.SearchCursor(table, fields)
    k=-1
    for k, row in enumerate(cursor): 
        print(row)
        break
    del cursor
    
    # if no rows
    if k == -1:
        cursor = arcpy.da.InsertCursor(table, fields)
        cursor.insertRow(["", "", ""]) 
        del cursor
    else: 
        with arcpy.da.UpdateCursor(table, fields) as cursor:
            for row in cursor:
                if None in row: cursor.updateRow(["","",""])
                break # look at the 1st row only 
        del cursor

r'''
class speckleInputsClass:
    #def __init__(self):
    print("CREATING speckle inputs first time________")
    instances = []
    accounts: List[Account] = get_local_accounts()
    account = None
    streams_default: Optional[List[Stream]] = None

    project = None
    active_map = None
    saved_streams: List[Optional[Tuple[StreamWrapper, Stream]]] = []
    stream_file_path: str = ""
    all_layers: List[arcLayer] = []
    clients: List[SpeckleClient] = []

    for acc in accounts:
        if acc.isDefault: account = acc
        new_client = SpeckleClient(
            acc.serverInfo.url,
            acc.serverInfo.url.startswith("https")
        )
        new_client.authenticate_with_token(token=acc.token)
        clients.append(new_client)

    speckle_client = None
    if account:
        speckle_client = SpeckleClient(
            account.serverInfo.url,
            account.serverInfo.url.startswith("https")
    )
        speckle_client.authenticate_with_token(token=account.token)
        streams_default = speckle_client.stream.search("")

    def __init__(self) -> None:
        print("___start speckle inputs________")
        self.all_layers = []
        try:
            aprx = ArcGISProject('CURRENT')
            self.project = aprx
            # following will fail if no project found 
            self.active_map = aprx.activeMap
            
            if self.active_map is not None and isinstance(self.active_map, Map): # if project loaded
                for layer in self.active_map.listLayers(): 
                    try: geomType = arcpy.Describe(layer.dataSource).shapeType.lower()
                    except: geomType = '' #print(arcpy.Describe(layer.dataSource)) #and arcpy.Describe(layer.dataSource).shapeType.lower() != "multipatch")
                    if (layer.isFeatureLayer and geomType != "multipatch") or layer.isRasterLayer: self.all_layers.append(layer) #type: 'arcpy._mp.Layer'
            self.stream_file_path: str = aprx.filePath.replace("aprx","gdb") + "\\speckle_streams.txt"

            if os.path.exists(self.stream_file_path): 
                try: 
                    f = open(self.stream_file_path, "r")
                    content = f.read()
                    self.saved_streams = self.getProjectStreams(content)
                    f.close()
                except: pass
                
            elif len(self.stream_file_path) >10: 
                f = open(self.stream_file_path, "x")
                f.close()
                f = open(self.stream_file_path, "w")
                content = ""
                f.write(content)
                f.close()
        except: self.project = None; print("Project not found")
        self.instances.append(self)

    def getProjectStreams(self, content: str = None):
        print("get proj streams")
        if not content: 
            content = self.stream_file_path
            try: 
                f = open(self.stream_file_path, "r")
                content = f.read()
                f.close()
            except: pass

        ######### need to check whether saved streams are available (account reachable)
        if content:
            streamsTuples = []
            for i, url in enumerate(content.split(",")):

                streamExists = 0
                index = 0
                try:
                    #print(url)
                    sw = StreamWrapper(url)
                    stream = self.tryGetStream(sw)

                    for st in streamsTuples: 
                        if isinstance(stream, Stream) and st[0].stream_id == stream.id: 
                            streamExists = 1; 
                            break 
                        index += 1
                    if streamExists == 1: del streamsTuples[index]
                    streamsTuples.insert(0,(sw, stream))

                except SpeckleException as e:
                    arcpy.AddMessage(str(e.args))
            return streamsTuples
        else: return []

    def tryGetStream (self,sw: StreamWrapper) -> Stream:
        if isinstance(sw, StreamWrapper):
            steamId = sw.stream_id
            try: steamId = sw.stream_id.split("/streams/")[1].split("/")[0] 
            except: pass

            client = sw.get_client()
            stream = client.stream.get(id = steamId, branch_limit = 100, commit_limit = 100)
            if isinstance(stream, GraphQLException):
                raise SpeckleException(stream.errors[0]['message'])
            return stream
        else: 
            raise SpeckleException('Invalid StreamWrapper provided')

class toolboxInputsClass:

    print("CREATING UI inputs first time________")
    instances = []
    lat: float = 0.0
    lon: float = 0.0
    active_stream: Optional[Stream] = None
    active_stream_wrapper: Optional[StreamWrapper] = None
    active_branch: Optional[Branch] = None
    active_commit = None
    selected_layers: List[Any] = []
    messageSpeckle: str = ""
    action: int = 1 #send
    project = None
    stream_file_path: str = ""
    # Get the target item's Metadata object
    
    def __init__(self) -> None:
        print("___start UI inputs________")
        try:
            aprx = ArcGISProject('CURRENT')
            project = aprx
            self.stream_file_path: str = aprx.filePath.replace("aprx","gdb") + "\\speckle_streams.txt"
            if os.path.exists(self.stream_file_path): 
                try: 
                    f = open(self.stream_file_path, "r")
                    content = f.read()
                    self.lat, self.lon = self.get_survey_point(content)
                    f.close()
                except: pass
        except: print("Project not found")
        try:
            aprx = ArcGISProject('CURRENT')
            self.project = aprx
        except: self.project = None; print("Project not found"); arcpy.AddWarning("Project not found")
        self.instances.append(self)

    def setProjectStreams(self, wr: StreamWrapper, add = True): 
        # ERROR 032659 Error queueing metrics request: 
        print("SET proj streams")

        if os.path.exists(self.stream_file_path) and ".gdb\\speckle_streams.txt" in self.stream_file_path: 

            new_content = ""

            f = open(self.stream_file_path, "r")
            existing_content = f.read()
            f.close()

            f = open(self.stream_file_path, "w")
            if str(wr.stream_url) in existing_content: 
                new_content = existing_content.replace(str(wr.stream_url) + "," , "")
            else: 
                new_content = existing_content 
            
            if add == True: new_content += str(wr.stream_url) + "," # add stream
            else: pass # remove stream

            f.write(new_content)
            f.close()
        elif ".gdb\\speckle_streams.txt" in self.stream_file_path: 
            f = open(self.stream_file_path, "x")
            f.close()
            f = open(self.stream_file_path, "w")
            f.write(str(wr.stream_url) + ",")
            f.close()
 
    def get_survey_point(self, content = None) -> Tuple[float]:
        # get from saved project 
        print("get survey point")
        x = y = 0
        if not content: 
            content = None 
            if os.path.exists(self.stream_file_path) and ".gdb\\speckle_streams.txt" in self.stream_file_path: 
                try: 
                    f = open(self.stream_file_path, "r")
                    content = f.read()
                    f.close()
                except: pass
        if content:
            for i, coords in enumerate(content.split(",")):
                if "speckle_sr_origin_" in coords: 
                    try:
                        x, y = [float(c) for c in coords.replace("speckle_sr_origin_","").split(";")]
                    except: pass
        return (x, y) 

    def set_survey_point(self, coords: List[float]):
        # from widget (2 strings) to local vars + update SR of the map
        print("SET survey point")

        if len(coords) == 2: 
            pt = "speckle_sr_origin_" + str(coords[0]) + ";" + str(coords[1]) 
            if os.path.exists(self.stream_file_path) and ".gdb\\speckle_streams.txt" in self.stream_file_path: 

                new_content = ""
                f = open(self.stream_file_path, "r")
                existing_content = f.read()
                f.close()

                f = open(self.stream_file_path, "w")
                if pt in existing_content: 
                    new_content = existing_content.replace( pt , "")
                else: 
                    new_content = existing_content 
                
                new_content += pt + "," # add point
                f.write(new_content)
                f.close()
            elif ".gdb\\speckle_streams.txt" in self.stream_file_path: 
                f = open(self.stream_file_path, "x")
                f.close()
                f = open(self.stream_file_path, "w")
                f.write(pt + ",")
                f.close()
            
            # save to project; crearte SR
            self.lat, self.lon = coords[0], coords[1]
            newCrsString = "+proj=tmerc +ellps=WGS84 +datum=WGS84 +units=m +no_defs +lon_0=" + str(self.lon) + " lat_0=" + str(self.lat) + " +x_0=0 +y_0=0 +k_0=1"
            newCrs = osr.SpatialReference()
            newCrs.ImportFromProj4(newCrsString)
            newCrs.MorphToESRI() # converts the WKT to an ESRI-compatible format
            

            validate = True if len(newCrs.ExportToWkt())>10 else False

            if validate: 
                newProjSR = arcpy.SpatialReference()
                newProjSR.loadFromString(newCrs.ExportToWkt())

                #source = osr.SpatialReference() 
                #source.ImportFromWkt(self.project.activeMap.spatialReference.exportToString())
                #transform = osr.CoordinateTransformation(source, newCrs)

                self.project.activeMap.spatialReference =  newProjSR
                arcpy.AddMessage("Custom project CRS successfully applied")
            else:
                arcpy.AddWarning("Custom CRS could not be created")
        
        else:
            arcpy.AddWarning("Custom CRS could not be created: not enough coordinates provided")

        return True
'''
    