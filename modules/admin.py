import streamlit as st
import pandas as pd
import json
import requests
import os
from datetime import datetime, date
# import folium # Remove Folium
# from streamlit_folium import folium_static # Remove streamlit_folium_static
import pydeck as pdk # Add PyDeck if specific types from it are needed, though helpers are in streamlit_app
import plotly.express as px # Keep for other plots if any, though not used in current admin view
from io import BytesIO
from utils.map_utils import update_map_view_to_project_bounds
from config import API_URL  # Import centralized config

# Import helper functions from streamlit_app.py (conceptual import - they are globally available)
# For a cleaner structure later, these could be in a utils.py file and imported explicitly.
# from streamlit_app import update_map_view_to_project_bounds, create_geojson_feature, create_pydeck_geojson_layer

# API_URL is now imported from config.py

def create_geojson_feature(geometry, properties=None):
    '''Wraps a GeoJSON geometry into a GeoJSON Feature structure.'''
    if properties is None: properties = {}
    return {"type": "Feature", "geometry": geometry, "properties": properties}

def create_pydeck_geojson_layer(
    data, layer_id, fill_color=[255, 255, 255, 100], line_color=[0, 0, 0, 200],
    line_width_min_pixels=1, get_line_width=10, opacity=0.5, stroked=True, filled=True,
    extruded=False, wireframe=True, pickable=False, tooltip_html=None, auto_highlight=True,
    highlight_color=[0, 0, 128, 128]
):
    '''Creates a PyDeck GeoJsonLayer with specified parameters.'''
    layer_config = {
        "id": layer_id, "data": data, "opacity": opacity, "stroked": stroked, "filled": filled,
        "extruded": extruded, "wireframe": wireframe, "get_fill_color": fill_color,
        "get_line_color": line_color, "get_line_width": get_line_width,
        "line_width_min_pixels": line_width_min_pixels, "pickable": pickable,
        "auto_highlight": auto_highlight, "highlight_color": highlight_color
    }
    if tooltip_html and pickable: layer_config["tooltip"] = {"html": tooltip_html}
    return pdk.Layer("GeoJsonLayer", **layer_config)
# --- End PyDeck Map Helper Functions ---

def geojson_to_feature_list(geojson_input, default_properties=None):
    """Converts various GeoJSON input types to a list of GeoJSON Features."""
    if default_properties is None:
        default_properties = {}
    
    features = []
    if not geojson_input: # Handle empty or None input
        return []

    if isinstance(geojson_input, dict):
        if geojson_input.get("type") == "FeatureCollection":
            features.extend(geojson_input.get("features", []))
        elif geojson_input.get("type") == "Feature":
            features.append(geojson_input)
        elif geojson_input.get("type") in ["Polygon", "MultiPolygon", "LineString", "MultiLineString", "Point", "MultiPoint"]:
            # It's a raw geometry, wrap it in a Feature
            features.append(create_geojson_feature(geojson_input, default_properties))
        else:
            # Try to handle as a list of geometries if it's a dict with a list of coords (older format?)
            if "coordinates" in geojson_input: # Heuristic for simple geometry dicts
                 features.append(create_geojson_feature(geojson_input, default_properties))
    elif isinstance(geojson_input, list):
        # If it's a list, assume it's a list of Features or a list of Geometries
        for item in geojson_input:
            if isinstance(item, dict):
                if item.get("type") == "Feature":
                    features.append(item)
                elif item.get("type") in ["Polygon", "MultiPolygon", "LineString", "MultiLineString", "Point", "MultiPoint"]:
                    features.append(create_geojson_feature(item, default_properties))
                elif "coordinates" in item: # Heuristic for simple geometry dicts in a list
                    features.append(create_geojson_feature(item, default_properties))
    return features

def show_admin():
    """Main admin function to handle project selection and display admin panel"""
    # Set widget width for admin
    st.session_state.widget_width_percent = 50
    
    if "projects" not in st.session_state or not st.session_state.projects:
        if not refresh_projects():
            st.markdown("<h2 style='text-align: center; color: white;'>Admin-Panel</h2>", unsafe_allow_html=True)
            st.warning("Projekte konnten nicht geladen werden. Bitte stellen Sie sicher, dass das Backend läuft und erreichbar ist.")
            st.session_state.map_layers = [] # Clear map layers
            return
    
    if "current_project" in st.session_state and st.session_state.current_project is not None:
        selected_project = st.session_state.current_project
        st.markdown(f"<h2 style='text-align: center;'>Admin: {selected_project['name']}</h2>", unsafe_allow_html=True)
        show_admin_panel(selected_project)
    else:
        st.markdown("<h2 style='text-align: center;'>Admin-Panel</h2>", unsafe_allow_html=True)
        st.info("Bitte wählen Sie ein Projekt aus der Seitenleiste oder erstellen Sie ein neues auf der Projekteinrichtungs-Seite.")
        st.session_state.map_layers = [] # Clear map if no project selected

def show_admin_panel(project):
    """Show the admin panel for managing an existing project, updating map layers."""
    # Update map view to project bounds - only once per project load on this page
    admin_view_key = f"admin_view_set_{project.get('id')}"
    if admin_view_key not in st.session_state:
        # Direkt den Helfer nutzen, um einen zirkulären Import zu verhindern
        update_map_view_to_project_bounds(project.get("map_bounds"))
        st.session_state[admin_view_key] = True

    # Prepare layers for PyDeck map
    admin_map_layers = []

    # 1. Construction Site Polygon
    polygon_geojson = project.get("polygon")
    if polygon_geojson and polygon_geojson.get("coordinates"):
        site_features = geojson_to_feature_list(polygon_geojson, {"name": "Baustelle", "type": "Baustelle"})
        if site_features:
            admin_map_layers.append(create_pydeck_geojson_layer(
                data=site_features,
                layer_id="admin_construction_site",
                fill_color=[70, 130, 180, 160],  # Reddish
                line_color=[70, 130, 180, 160],
                line_width_min_pixels=2,
                pickable=True,
                tooltip_html="<b>{properties.name}</b><br/>Typ: {properties.type}"
            ))

    # 2. Waiting Areas
    waiting_areas_geojson = project.get("waiting_areas") # This might be a FeatureCollection or a list of Polygons
    if waiting_areas_geojson:
        waiting_features = geojson_to_feature_list(waiting_areas_geojson, {"name": "Wartebereich", "type": "Wartebereich"})
        if waiting_features: # Ensure we have features to add
            admin_map_layers.append(create_pydeck_geojson_layer(
                data=waiting_features,
                layer_id="admin_waiting_areas",
                fill_color=[0, 123, 255, 160],  # Blueish
                line_color=[0, 123, 255, 255],
                pickable=True,
                tooltip_html="<b>{properties.name}</b><br/>Typ: {properties.type}"
            ))

    # 3. Access Routes
    access_routes_geojson = project.get("access_routes") # Might be FeatureCollection or list of LineStrings
    if access_routes_geojson:
        route_features = geojson_to_feature_list(access_routes_geojson, {"name": "Zufahrtsroute", "type": "Route"})
        if route_features:
            admin_map_layers.append(create_pydeck_geojson_layer(
                data=route_features,
                layer_id="admin_access_routes",
                fill_color=[40, 167, 69, 160], # Greenish (used for line) - not filled for lines
                line_color=[40, 167, 69, 255], 
                stroked=True, # Ensure lines are drawn
                filled=False, # Lines are not typically filled
                line_width_min_pixels=3,
                pickable=True,
                tooltip_html="<b>{properties.name}</b><br/>Typ: {properties.type}"
            ))

    # 4. Map Bounds (optional visualization)
    map_bounds_geojson = project.get("map_bounds")
    if map_bounds_geojson and map_bounds_geojson.get("coordinates"):
        bounds_features = geojson_to_feature_list(map_bounds_geojson, {"name": "Kartenanzeigegrenzen", "type": "Grenzen"})
        if bounds_features:
            admin_map_layers.append(create_pydeck_geojson_layer(
                data=bounds_features,
                layer_id="admin_map_bounds",
                fill_color=[108, 117, 125, 70],  # Greyish, very transparent
                line_color=[108, 117, 125, 150],
                line_width_min_pixels=2,
                pickable=True,
                tooltip_html="<b>{properties.name}</b><br/>Typ: {properties.type}"
            ))
    
    # Update map layers in session state
    st.session_state.map_layers = admin_map_layers
    
    # Create tabs for different admin functions
    tab1, tab2, tab3 = st.tabs([
        "Projekt bearbeiten", 
        "Excel aktualisieren", 
        "Simulationseinstellungen"
    ])
    
    with tab1:
        st.subheader("Projektdetails bearbeiten")
        new_name = st.text_input("Projektname", value=project["name"])
        
        st.subheader("Geometrien bearbeiten")
        st.markdown("Die Projektgeometrien werden auf der Hauptkarte angezeigt. Um sie zu bearbeiten, verwenden Sie die untenstehenden Textbereiche. Nach der Aktualisierung wird die Karte aktualisiert.")
        
        # Use a different approach for the text areas with more space
        st.markdown("<div style='display: flex; flex-wrap: wrap; gap: 20px;'>", unsafe_allow_html=True)
        
        # First column - Construction Site and Waiting Areas
        st.markdown("<div style='flex: 1; min-width: 45%;'>", unsafe_allow_html=True)
        st.markdown("<h6>Baustellen-Polygon:</h6>", unsafe_allow_html=True)
        polygon_json_initial = json.dumps(project.get("polygon", {}), indent=2)
        polygon_json = st.text_area("GeoJSON für Baustelle", value=polygon_json_initial, height=200, key=f"poly_json_{project['id']}")
        
        st.markdown("<h6 style='margin-top: 20px;'>Wartebereiche:</h6>", unsafe_allow_html=True)
        waiting_areas_initial = json.dumps(project.get("waiting_areas", []), indent=2)
        waiting_areas_json = st.text_area("GeoJSON für Wartebereiche", value=waiting_areas_initial, height=200, key=f"wait_json_{project['id']}")
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Second column - Access Routes and Map Bounds
        st.markdown("<div style='flex: 1; min-width: 45%;'>", unsafe_allow_html=True)
        st.markdown("<h6>Zufahrtsrouten:</h6>", unsafe_allow_html=True)
        access_routes_initial = json.dumps(project.get("access_routes", []), indent=2)
        access_routes_json = st.text_area("GeoJSON für Zufahrtsrouten", value=access_routes_initial, height=200, key=f"route_json_{project['id']}")
        
        st.markdown("<h6 style='margin-top: 20px;'>Kartengrenzen:</h6>", unsafe_allow_html=True)
        map_bounds_initial = json.dumps(project.get("map_bounds", {}), indent=2)
        map_bounds_json = st.text_area("GeoJSON für Kartengrenzen", value=map_bounds_initial, height=200, key=f"bounds_json_{project['id']}")
        st.markdown("</div>", unsafe_allow_html=True)
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        if st.button("Projektdetails & Geometrien aktualisieren"): # Changed button label for clarity
            try:
                polygon_data = json.loads(polygon_json) if polygon_json.strip() else {}
                waiting_areas_data = json.loads(waiting_areas_json) if waiting_areas_json.strip() else []
                access_routes_data = json.loads(access_routes_json) if access_routes_json.strip() else []
                map_bounds_data = json.loads(map_bounds_json) if map_bounds_json.strip() else {}
                
                # Validate GeoJSON structure (basic check)
                # More thorough validation would involve jsonschema or similar
                for geo_data, name in [
                    (polygon_data, "Polygon"), (map_bounds_data, "Kartengrenzen")
                ]:
                    if geo_data and (not isinstance(geo_data, dict) or "type" not in geo_data or "coordinates" not in geo_data):
                        st.error(f"Ungültige GeoJSON-Struktur für {name}. Stellen Sie sicher, dass sie 'type' und 'coordinates' hat.")
                        return # Stop processing
                for geo_list, name in [
                    (waiting_areas_data, "Wartebereiche"), (access_routes_data, "Zufahrtsrouten")
                ]:
                    if geo_list and not isinstance(geo_list, list): # Should be list of Features/Geometries or FC
                        # Could also be a single FeatureCollection
                        if not (isinstance(geo_list, dict) and geo_list.get("type") == "FeatureCollection"):
                            st.error(f"Ungültige GeoJSON-Struktur für {name}. Erwartet wird eine Liste von Geometrien/Features oder eine FeatureCollection.")
                            return

                form_data = {
                    "name": new_name,
                    "polygon": json.dumps(polygon_data),
                    "waiting_areas": json.dumps(waiting_areas_data),
                    "access_routes": json.dumps(access_routes_data),
                    "map_bounds": json.dumps(map_bounds_data)
                }
                
                response = requests.put(f"{API_URL}/api/projects/{project['id']}", data=form_data)
                
                if response.status_code == 200:
                    updated_project = response.json()
                    st.success("Projekt erfolgreich aktualisiert!")
                    st.session_state.current_project = updated_project
                    refresh_projects() # Update projects list in session state
                     # Clear view set flag to re-trigger map centering if bounds changed
                    if f"admin_view_set_{project['id']}" in st.session_state: 
                        del st.session_state[f"admin_view_set_{project['id']}"]
                    if f"dashboard_view_set_{project['id']}" in st.session_state: 
                        del st.session_state[f"dashboard_view_set_{project['id']}"]
                    if f"resident_info_view_set_{project['id']}" in st.session_state: 
                        del st.session_state[f"resident_info_view_set_{project['id']}"]
                    st.rerun()
                else:
                    st.error(f"Projekt konnte nicht aktualisiert werden: {response.status_code} - {response.text}")
            except json.JSONDecodeError as e:
                st.error(f"Ungültiges GeoJSON-Format in einem der Textbereiche: {str(e)}")
            except Exception as e:
                st.error(f"Fehler beim Aktualisieren des Projekts: {str(e)}")
    
    with tab2:
        st.subheader("Excel-Daten aktualisieren")
        st.info(f"Aktuelle Excel-Datei: {project.get('file_name', 'N/A')}")
        uploaded_file = st.file_uploader("Neue Excel-Datei auswählen", type=["xlsx"], key=f"excel_upload_{project['id']}")
        
        if uploaded_file is not None:
            try:
                st.markdown("<h6>Datenvorschau (Erste 5 Zeilen)</h6>", unsafe_allow_html=True)
                deliveries_df = pd.read_excel(uploaded_file, sheet_name="Deliveries")
                schedule_df = pd.read_excel(uploaded_file, sheet_name="Schedule")
                vehicles_df = pd.read_excel(uploaded_file, sheet_name="Vehicles")
                uploaded_file.seek(0)
                with st.expander("Lieferungen Vorschau"): st.dataframe(deliveries_df.head())
                with st.expander("Zeitplan Vorschau"): st.dataframe(schedule_df.head())
                with st.expander("Fahrzeuge Vorschau"): st.dataframe(vehicles_df.head())
                
                if st.button("Excel-Daten aktualisieren"):
                    try:
                        files = {"file": (uploaded_file.name, uploaded_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
                        response = requests.put(f"{API_URL}/api/projects/{project['id']}", files=files)
                        if response.status_code == 200:
                            updated_project = response.json()
                            st.success("Excel-Daten erfolgreich aktualisiert!")
                            st.session_state.current_project = updated_project
                            refresh_projects()
                            st.rerun()
                        else:
                            st.error(f"Excel-Daten konnten nicht aktualisiert werden: {response.status_code} - {response.text}")
                    except Exception as e:
                        st.error(f"Fehler beim Aktualisieren der Excel-Daten: {str(e)}")
            except Exception as e:
                st.error(f"Fehler beim Lesen der Excel-Datei: {str(e)}")
    
    with tab3:
        st.subheader("Simulationseinstellungen")
        # ... (Simulation Settings content remains largely the same as it doesn't involve maps directly)
        st.info(f"Aktuelle Simulationseinstellungen: Start: {project.get('simulation_start_time', '06:00')}, Ende: {project.get('simulation_end_time', '18:00')}, Intervall: {project.get('simulation_interval', '1h')}")
        
        # Use a better layout with more space between inputs
        st.markdown("<div style='display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 20px;'>", unsafe_allow_html=True)
        
        # Start Time
        st.markdown("<div style='flex: 1; min-width: 30%;'>", unsafe_allow_html=True)
        st.markdown("<label>Startzeit (HH:MM)</label>", unsafe_allow_html=True)
        start_time = st.text_input("starttime", value=project.get('simulation_start_time', '06:00'), key=f"sim_start_{project['id']}", label_visibility="collapsed")
        st.markdown("</div>", unsafe_allow_html=True)
        
        # End Time
        st.markdown("<div style='flex: 1; min-width: 30%;'>", unsafe_allow_html=True)
        st.markdown("<label>Endzeit (HH:MM)</label>", unsafe_allow_html=True)
        end_time = st.text_input("endtime", value=project.get('simulation_end_time', '18:00'), key=f"sim_end_{project['id']}", label_visibility="collapsed")
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Interval
        st.markdown("<div style='flex: 1; min-width: 30%;'>", unsafe_allow_html=True)
        st.markdown("<label>Intervall</label>", unsafe_allow_html=True)
        interval = st.selectbox("selectbox", options=["15m", "30m", "1h", "2h", "4h"], index=2, key=f"sim_interval_{project['id']}", label_visibility="collapsed") # Default to 1h
        st.markdown("</div>", unsafe_allow_html=True)
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        if st.button("Simulationseinstellungen aktualisieren"):
            try:
                form_data = {"simulation_start_time": start_time, "simulation_end_time": end_time, "simulation_interval": interval}
                response = requests.put(f"{API_URL}/api/projects/{project['id']}", data=form_data)
                if response.status_code == 200:
                    updated_project = response.json()
                    st.success("Simulationseinstellungen erfolgreich aktualisiert!")
                    st.session_state.current_project = updated_project
                    refresh_projects()
                    st.rerun()
                else:
                    st.error(f"Simulationseinstellungen konnten nicht aktualisiert werden: {response.status_code} - {response.text}")
            except Exception as e:
                st.error(f"Fehler beim Aktualisieren der Simulationseinstellungen: {str(e)}")
        
        st.markdown("<hr style='margin-top: 10px; margin-bottom: 10px;'>", unsafe_allow_html=True)
        st.subheader("Simulation ausführen")
        col1, col2 = st.columns(2)
        with col1: start_date_sim = st.date_input("Startdatum", value=date.today(), key=f"sim_date_start_{project['id']}")
        with col2: end_date_sim = st.date_input("Enddatum", value=date.today() + pd.Timedelta(days=7), key=f"sim_date_end_{project['id']}")
        
        if st.button("Simulation starten"):
            try:
                simulation_request = {"project_id": project["id"], "start_date": start_date_sim.isoformat(), "end_date": end_date_sim.isoformat(), "time_interval": interval}
                with st.spinner("Simulation läuft... Dies kann einige Minuten dauern."):
                    response = requests.post(f"{API_URL}/api/simulation/run", json=simulation_request)
                    if response.status_code == 200:
                        simulation_result = response.json()
                        st.success("Simulation erfolgreich abgeschlossen!")
                        st.subheader("Simulationszusammenfassung")
                        st.json(simulation_result.get("stats", "Keine Statistiken verfügbar."))
                        st.info("Detaillierte Ergebnisse im Dashboard anzeigen.")
                        if st.button("Zum Dashboard"):
                            st.session_state.page = "dashboard"
                            st.rerun()
                    else:
                        st.error(f"Simulation konnte nicht ausgeführt werden: {response.status_code} - {response.text}")
            except Exception as e:
                st.error(f"Fehler beim Ausführen der Simulation: {str(e)}")

def refresh_projects():
    """Refresh the projects list in the session state"""
    try:
        response = requests.get(f"{API_URL}/api/projects/")
        if response.status_code == 200:
            st.session_state.projects = response.json()
            if not st.session_state.projects: st.session_state.projects = [] # Ensure it's a list
            return True
        else:
            st.error(f"Projekte konnten nicht aktualisiert werden: {response.status_code}")
            st.session_state.projects = []
            return False
    except Exception as e:
        st.error(f"Fehler beim Verbinden zur API: {str(e)}")
        st.session_state.projects = []
        return False 