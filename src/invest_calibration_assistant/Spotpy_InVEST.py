# -*- coding: utf-8 -*-
# -------------------------------------------------------------------------
# Nature For Water Facility - The Nature Conservancy
# -------------------------------------------------------------------------
# InVEST - Version 3.15.1 (update July 2025)
# -------------------------------------------------------------------------
#                           BASIC INFORMATION
# -------------------------------------------------------------------------
# Author        : Jonathan Nogales Pimentel
# Email         : jonathan.nogales@tnc.org
# Date          : October, 2024
#
# -------------------------------------------------------------------------
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or option) any
# later version. This program is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# ee the GNU General Public License for more details. You should have
# received a copy of the GNU General Public License along with this program.
# If not, see http://www.gnu.org/licenses/.
# -------------------------------------------------------------------------
#                            DESCRIPTION
# -------------------------------------------------------------------------
# This code allow

# -------------------------------------------------------------------------
#                             REFERENCES
# -------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------------------------------------
# Package
# ----------------------------------------------------------------------------------------------------------------------
import os, sys
import spotpy
import numpy as np
import pandas as pd
import geopandas as gpd
import win32com.client
from simpledbf import Dbf5
from osgeo import gdal, ogr
from osgeo.gdalconst import *
import rasterio
import matplotlib.pyplot as plt
from matplotlib import rcParams
# Cambiar a Times New Roman para texto y matemáticas
rcParams['font.family'] = 'Times New Roman'
rcParams['mathtext.fontset'] = 'custom'
rcParams['mathtext.rm'] = 'Times New Roman'
rcParams['mathtext.it'] = 'Times New Roman:italic'
rcParams['mathtext.bf'] = 'Times New Roman:bold'
from rasterstats import zonal_stats
# Seasonal Water Yield
from natcap.invest.seasonal_water_yield import seasonal_water_yield as swy
# Sediment Delivery Ratio
from natcap.invest.sdr import sdr
# Nutrient Delivery Ratio
from natcap.invest.ndr import ndr
# Anual Water Yield
import natcap.invest.annual_water_yield as awy
# Carbons
from natcap.invest import carbon

gdal.PushErrorHandler('CPLQuietErrorHandler')

def CreateFolder(dir):
    try:
        os.makedirs(dir)
    except FileExistsError:
        # directory already exists
        pass

def RunCalInVEST(ProjectPath, InVEST_Main_Path, NameFunObj, NameOpt, NumSim=5):

    # ----------------------------------------------------------------------------------------------------------------------
    # Inputs
    # ----------------------------------------------------------------------------------------------------------------------
    Inputs = pd.read_excel(InVEST_Main_Path, sheet_name='UserData', index_col=0)

    # ----------------------------------------------------------------------------------------------------------------------
    # Configuración de calibración
    # ----------------------------------------------------------------------------------------------------------------------
    NModel = ['AWY', 'SWY', 'SDR', 'NDR_N', 'NDR_P']
    for i in range(0, len(NModel)):
        if Inputs.loc['Run', NModel[i]] == 1:

            # Nombre del modelo
            NameModel = NModel[i]

            if NameOpt == "Dynamical dimensional search (DDS)":
                FactorMetric = -1
            elif NameOpt == "Shuffled Complex Evolution (SCE-UA)":
                FactorMetric = 1
            elif NameOpt == "Latin Hypercube Sampling (LHS)":
                FactorMetric = 1

            # Crear Objecto - Spotpy para AWY
            spot_setup = Spotpy_InVEST(ProjectPath,
                                       InVEST_Main_Path,
                                       NameModel,
                                       NameFunObj,
                                       FactorMetric)

            # Almacenamiento de resultados
            results     = []
            # Número de simulaciones en calibración
            rep         = int(NumSim)
            # Timepo de salida de mensajes
            timeout     = 2
            # Ejecución en paralelo o secuencial
            parallel    = "seq"
            # Formato de salida
            dbformat    = "csv"

            # Configuración de caso de optimización
            if NameOpt == "Dynamical dimensional search (DDS)":
                # Directorio de resultados
                PathRestuls = os.path.join(ProjectPath, 'PARAMETERS', NameModel + '_DDS')
                sampler     = spotpy.algorithms.dds(spot_setup, parallel=parallel, dbname=PathRestuls, dbformat=dbformat,
                                                sim_timeout=timeout)
            elif NameOpt == "Shuffled Complex Evolution (SCE-UA)":
                # Directorio de resultados
                PathRestuls = os.path.join(ProjectPath, 'PARAMETERS', NameModel + '_SCE')
                sampler     = spotpy.algorithms.sceua(spot_setup, parallel=parallel, dbname=PathRestuls, dbformat=dbformat,
                                                sim_timeout=timeout)
            elif NameOpt == "Latin Hypercube Sampling (LHS)":
                # Directorio de resultados
                PathRestuls = os.path.join(ProjectPath, 'PARAMETERS', NameModel + '_LHS')
                sampler     = spotpy.algorithms.lhs(spot_setup, parallel=parallel, dbname=PathRestuls, dbformat=dbformat,
                                                sim_timeout=timeout)

            sampler.sample(rep)
            results.append(sampler.getdata())

            # Plot Results
            if NameFunObj == "Mean Square Error (MSE)":
                FO = "MSE"
            elif NameFunObj == "Mean Absolute Error (MAE)":
                FO = "MAE"
            elif NameFunObj == "Root Mean Square Error (RMSE)":
                FO = "RMSE"
            elif NameFunObj == "Relative Root Mean Squared Error (RRMSE)":
                FO = "RRMSE"

            # Gráficas de resultados (Scatter Plot)
            if NameModel == 'AWY':
                Plot_AWY(ProjectPath, Inputs.loc['Name', 'Value'], FO, InVEST_Main_Path, FactorMetric)
            if NameModel == 'SWY':
                Plot_SWY(ProjectPath, Inputs.loc['Name', 'Value'], FO, InVEST_Main_Path, FactorMetric)
            if NameModel == 'SDR':
                Plot_SDR(ProjectPath, Inputs.loc['Name', 'Value'], FO, InVEST_Main_Path, FactorMetric)
            if NameModel == 'NDR_N':
                Plot_NDR_N(ProjectPath, Inputs.loc['Name', 'Value'], FO, InVEST_Main_Path, FactorMetric)
            if NameModel == 'NDR_P':
                Plot_NDR_P(ProjectPath, Inputs.loc['Name', 'Value'], FO, InVEST_Main_Path, FactorMetric)

            # Execution Model whith best parameters
            RunInVEST(ProjectPath, InVEST_Main_Path)

            print('#################################################')
            print('   //////////   ')
            print('   |        |   ')
            print('  _|  _   _ |_  ')
            print(' |.|-(.)-(.)+.| ')
            print('  \\|    J   |/  ')
            print('   \\   ---  /   ')
            print('    \\      /    ')
            print('     "####"     ')
            print('successful calibration - ' + NameModel)
            print('#################################################')

def Create_argsInVEST(ProjectPath,UserData,Params,StatusK='SDR'):
    # ----------------------------------------------------------------------------------------------------------------------
    # Capas de entrada para modelos InVEST
    # ----------------------------------------------------------------------------------------------------------------------
    args = {}
    NL                                      = os.path.join(ProjectPath, 'INPUTS', 'LULC', UserData['LULC'] + '.tif')
    args['lulc_path']                       = NL
    args['lulc_raster_path']                = NL
    args['lulc_cur_path']                   = NL
    NB                                      = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '.csv')
    args['biophysical_table_path']          = NB
    args['carbon_pools_path']               = NB
    args['depth_to_root_rest_layer_path']   = os.path.join(ProjectPath, 'INPUTS', UserData['SoilDepth'] + '.tif')
    args['do_scarcity_and_valuation']       = False
    args['eto_path']                        = os.path.join(ProjectPath, 'INPUTS', UserData['ETP'] + '.tif')
    args['pawc_path']                       = os.path.join(ProjectPath, 'INPUTS', UserData['PAWC'] + '.tif')
    args['precipitation_path']              = os.path.join(ProjectPath, 'INPUTS', UserData['P'] + '.tif')
    args['results_suffix']                  = UserData['Suffix']
    args['sub_watersheds_path']             = os.path.join(ProjectPath, 'INPUTS', 'Basin', UserData['SubBasin'] + '.shp')
    args['watersheds_path']                 = os.path.join(ProjectPath, 'INPUTS', 'Basin', UserData['Basin'] + '.shp')
    args['aoi_path']                        = os.path.join(ProjectPath, 'INPUTS', 'Basin', UserData['Basin'] + '.shp')
    args['dem_raster_path']                 = os.path.join(ProjectPath, 'INPUTS', UserData['DEM'] + '.tif')
    args['et0_dir']                         = os.path.join(ProjectPath, 'INPUTS', UserData['ETP_Path'])
    args['monthly_alpha']                   = False
    args['precip_dir']                      = os.path.join(ProjectPath, 'INPUTS', UserData['P_Path'])
    args['rain_events_table_path']          = os.path.join(ProjectPath, 'INPUTS', UserData['RainTable'] + '.csv')
    args['soil_group_path']                 = os.path.join(ProjectPath, 'INPUTS', UserData['SoilGroup'] + '.tif')
    args['threshold_flow_accumulation']     = '%0.0f' % UserData['Threshold']
    args['user_defined_climate_zones']      = False
    args['user_defined_local_recharge']     = False
    args['dem_path']                        = os.path.join(ProjectPath, 'INPUTS', UserData['DEM'] + '.tif')
    args['drainage_path']                   = ''
    args['erodibility_path']                = os.path.join(ProjectPath, 'INPUTS', UserData['K'] + '.tif')
    args['erosivity_path']                  = os.path.join(ProjectPath, 'INPUTS', UserData['R'] + '.tif')
    args['runoff_proxy_path']               = os.path.join(ProjectPath, 'INPUTS', UserData['P'] + '.tif')
    args['calc_sequestration']              = False
    args['do_redd']                         = False
    args['do_valuation']                    = False
    args['flow_dir_algorithm']              = 'MFD'

    # AWY
    if StatusK == "AWY":
        args['seasonality_constant']            = '%0.2f' % Params['Z']

    # SWY
    if StatusK == "SWY":
        args['alpha_m']                         = '%0.3f' % Params['Alpha']
        args['beta_i']                          = '%0.3f' % Params['Beta']
        args['gamma']                           = '%0.3f' % Params['Gamma']

    # SDR
    if StatusK == "SDR":
        args['l_max']                           = '%0.2f' % Params['L_max']
        args['ic_0_param']                      = '%0.2f' % Params['IC0']
        args['sdr_max']                         = '%0.2f' % Params['sdr_max']

    # NDR
    if StatusK == "NDR_N":
        args['calc_n'] = True
        args['calc_p'] = False
        args['subsurface_critical_length_n']    = '%0.2f' % Params['Factor_Load_N']
        args['subsurface_eff_n']                = '%0.2f' % Params['Factor_Eff_N']

    if StatusK == "NDR_P":
        args['calc_n'] = False
        args['calc_p'] = True
        args['subsurface_critical_length_p']    = '%0.2f' % Params['Factor_Load_P']
        args['subsurface_eff_p']                = '%0.2f' % Params['Factor_Eff_P']

    if StatusK == 'SDR':
        args['k_param']                     = '%0.2f' % Params['Borselli-K_SDR']
    elif (StatusK == 'NDR_N') or (StatusK == 'NDR_P'):
        args['k_param']                     = '%0.2f' % Params['Borselli-K_NDR']

    return args

def Factor_BioTable(PathBioTable, Params, UserData):
    # --------------------------------------------------------------------------------------------------------------
    # Read Biophycial Table
    # --------------------------------------------------------------------------------------------------------------
    Table = pd.read_csv(PathBioTable, encoding='latin-1')

    # Anual Water Yield
    if UserData['Status_AWY']:
        # --------------------------------------------------------------------------------------------------------------
        # Afectación de parámetros Kc en la tabla biofísica
        # --------------------------------------------------------------------------------------------------------------
        # Aplica el factor multiplicador a los valores de carga y redondea a 3 decimales
        Values = round(Table['Kc'] * Params['Factor-Kc'], 2)
        # Si el factor hace que el Kc sea mayor que 1.2, limita el valor a 1.2
        Values[Values >= 1.2] = 1.2
        # Asigna los valores de Kc modificados a la tabla
        Table['Kc'].loc[Table['Status_Cal_Kc'] == 1] = Values.loc[Table['Status_Cal_Kc'] == 1]

    # Seasonal Water Yield
    if UserData['Status_SWY']:
        # --------------------------------------------------------------------------------------------------------------
        # Afectacion de parametros Kc en la tabla biofisica
        # --------------------------------------------------------------------------------------------------------------
        for ij in range(1, 13):
            # Aplica el factor multiplicador a los valores de carga y redondea a 3 decimales
            Values = round(Table['Kc_' + str(ij)] * round(Params['Factor-Kc_m'], 2), 2)
            # Si el factor hace que el Kc sea mayor que 1.2, limita el valor a 1.2
            Values[Values >= 1.2] = 1.2
            # Asigna los valores de Kc modificados a la tabla
            Table['Kc_' + str(ij)].loc[Table['Status_Cal_Kc'] == 1] = Values.loc[Table['Status_Cal_Kc'] == 1]

    # Sediment Delivery Ratio
    if UserData['Status_SDR'] == 1:
        # ---------------------------------------------------------------------
        # Afectacion de parametro de factor de cobertura en la tabla biofisica
        # ---------------------------------------------------------------------
        # Aplica el factor multiplicador a los valores del factor C y redondea a 5 decimales
        Values = round(Table['usle_c'] * round(Params['Factor-C'], 2), 5)
        # Si el factor hace que el C sea mayor que 1, limita el valor a 1
        Values[Values > 1] = 1
        # Asigna los valores de C modificados a la tabla
        Table['usle_c'].loc[Table['Status_Cal_C'] == 1] = Values.loc[Table['Status_Cal_C'] == 1]

        # Aplica el factor multiplicador a los valores del factor P y redondea a 2 decimales
        Values = round(Table['usle_p'] * round(Params['Factor-P'], 2), 2)
        # Si el factor hace que el P sea mayor que 1, limita el valor a 1
        Values[Values > 1] = 1
        # Asigna los valores de C modificados a la tabla
        Table['usle_p'].loc[Table['Status_Cal_P'] == 1] = Values.loc[Table['Status_Cal_P'] == 1]

    # Nutrient Delivery Ratio
    if (UserData['Status_NDR_N'] == 1):
        # --------------------------------------------------------------------------------------------------------------
        #  Afectacion de parametros de carga de niotrogeno en la tabla biofisica
        # --------------------------------------------------------------------------------------------------------------
        # Aplica el factor multiplicador a los valores de carga y redondea a 3 decimales
        Values = round(Table['load_n'] * Params['Factor_Load_N'], 3)
        # Asigna los valores de load_n modificados a la tabla
        Table['load_n'].loc[Table['Status_Cal_Load_N'] == 1] = Values.loc[Table['Status_Cal_Load_N'] == 1]
        # Asigna los valores de carga modificados a la tabla
        Table['load_n'] = Values

        # --------------------------------------------------------------------------------------------------------------
        # Afectacion de parametros de eficiencia de retencion de nitrogeno en la tabla biofisica
        # --------------------------------------------------------------------------------------------------------------
        # Aplica el factor multiplicador a los valores de eficiencia y redondea a 2 decimales
        Values = round(Table['eff_n'] * Params['Factor_Eff_N'], 2)
        # Asigna los valores de eff_n modificados a la tabla
        Table['eff_n'].loc[Table['Status_Cal_Eff_N'] == 1] = Values.loc[Table['Status_Cal_Eff_N'] == 1]
        # Asigna los valores de carga modificados a la tabla
        Table['eff_n'] = Values

    if (UserData['Status_NDR_P'] == 1):
        # --------------------------------------------------------------------------------------------------------------
        #  Afectacion de parametros de carga de niotrogeno en la tabla biofisica
        # --------------------------------------------------------------------------------------------------------------
        # Aplica el factor multiplicador a los valores de carga y redondea a 3 decimales
        Values = round(Table['load_p'] * Params['Factor_Load_P'], 3)
        # Asigna los valores de load_n modificados a la tabla
        Table['load_p'].loc[Table['Status_Cal_Load_P'] == 1] = Values.loc[Table['Status_Cal_Load_P'] == 1]
        # Asigna los valores de carga modificados a la tabla
        Table['load_p'] = Values

        # --------------------------------------------------------------------------------------------------------------
        # Afectacion de parametros de eficiencia de retencion de nitrogeno en la tabla biofisica
        # --------------------------------------------------------------------------------------------------------------
        # Aplica el factor multiplicador a los valores de eficiencia y redondea a 2 decimales
        Values = round(Table['eff_p'] * Params['Factor_Eff_P'], 2)
        # Asigna los valores de eff_n modificados a la tabla
        Table['eff_p'].loc[Table['Status_Cal_Eff_P'] == 1] = Values.loc[Table['Status_Cal_Eff_P'] == 1]
        # Asigna los valores de carga modificados a la tabla
        Table['eff_p'] = Values

    # Carbons
    # if UserData['Status_CO2'] == 1:
    #    print('')

    return Table

def RunInVEST(ProjectPath, InVEST_Main_Path, BatchMode=False):
    """

    Parameters
    ----------
    ProjectPath
        Path project
    InVEST_Main_Path
        Path Main Project
    Returns
    -------

    """
    # ----------------------------------------------------------------------------------------------------------------------
    # Directorio de trabajo
    # ----------------------------------------------------------------------------------------------------------------------
    CreateFolder(os.path.join(ProjectPath, 'OUTPUTS'))

    # Read parameters
    Params      = Read_Parameters_InVEST(InVEST_Main_Path)

    print('Load Parameters - Ok')

    # Read user Data
    UserData    = Read_Inputs_InVEST(InVEST_Main_Path)

    print('Load Inputs - Ok')

    # ----------------------------------------------------------------------------------------------------------------------
    # Read List LULC
    # ----------------------------------------------------------------------------------------------------------------------
    if BatchMode:
        Tmp         = pd.read_excel(InVEST_Main_Path, sheet_name='LULC_Batch')
        List_LULC   = Tmp['Name LULC']
    else:
        List_LULC   = [UserData['LULC']]

    for LULC in List_LULC:
        NL  = os.path.join(ProjectPath, 'INPUTS', 'LULC', LULC + '.tif')

        print('----------------------------')
        print('Execution used: ' + LULC)
        print('----------------------------')

        NameModel = ''

        # --------------------------------------------------------------------------------------------------------------
        # Read Biophycial Table
        # --------------------------------------------------------------------------------------------------------------
        PathBioTable = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '.csv')

        # Anual Water Yield
        if UserData['Status_AWY'] == 1:
            print('----------------------------')
            print('Run AWY')
            print('----------------------------')

            # Aplicar factores a la tabla biofisica
            Table = Factor_BioTable(PathBioTable, Params, UserData)

            # --------------------------------------------------------------------------------------------------------------
            # Guardar Table Biofisica temporal
            # --------------------------------------------------------------------------------------------------------------
            PathTable = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '_Execution_AWY' + '.csv')
            Table.to_csv(PathTable, index=False)

            # Create args
            args = Create_argsInVEST(ProjectPath, UserData, Params, StatusK="AWY")

            # LULC
            args['lulc_path']           = NL
            args['lulc_raster_path']    = NL
            args['lulc_cur_path']       = NL

            # Biophysical Table Path
            args['biophysical_table_path']  = PathTable

            # Project Path
            args['workspace_dir']           = os.path.join(ProjectPath, 'OUTPUTS', '01-AWY', LULC) if BatchMode else os.path.join(ProjectPath, 'OUTPUTS', '01-AWY')
            args['results_suffix']          = LULC if BatchMode else UserData['Suffix']

            # Run AWY
            awy.execute(args)

            # Name model
            NameModel = NameModel + '| AWY |'

        # Seasonal Water Yield
        if UserData['Status_SWY'] == 1:
            print('----------------------------')
            print('Run SWY')
            print('----------------------------')

            # Aplicar factores a la tabla biofisica
            Table = Factor_BioTable(PathBioTable, Params, UserData)

            # --------------------------------------------------------------------------------------------------------------
            # Guardar Table Biofisica temporal
            # --------------------------------------------------------------------------------------------------------------
            PathTable = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '_Execution_SWY' + '.csv')
            Table.to_csv(PathTable, index=False)

            # Create args
            args = Create_argsInVEST(ProjectPath, UserData, Params, StatusK="SWY")

            # LULC
            args['lulc_path']           = NL
            args['lulc_raster_path']    = NL
            args['lulc_cur_path']       = NL

            # Biophysical Table Path
            args['biophysical_table_path']  = PathTable

            # Project Path
            args['workspace_dir']           = os.path.join(ProjectPath, 'OUTPUTS', '02-SWY', LULC) if BatchMode else os.path.join(ProjectPath, 'OUTPUTS', '02-SWY')
            args['results_suffix']          = LULC if BatchMode else UserData['Suffix']

            # Run SWY
            swy.execute(args)

            # Model
            NameModel = NameModel + '| SWY |'

            # ETR zonal
            raster_path = os.path.join(args['workspace_dir'], 'intermediate_outputs','aet_' + args['results_suffix'] + '.tif')
            Watershed   = os.path.join(ProjectPath, 'INPUTS', 'Basin', UserData['Basin'] + '.shp')
            output_path = args['workspace_dir']
            calculate_zonal_stats(Watershed, raster_path, output_path, Suffix=LULC + "_SWY")

        # Sediment Delivery Ratio
        if UserData['Status_SDR'] == 1:
            print('----------------------------')
            print('Run SDR')
            print('----------------------------')

            # Aplicar factores a la tabla biofisica
            Table = Factor_BioTable(PathBioTable, Params, UserData)

            # --------------------------------------------------------------------------------------------------------------
            # Guardar Table Biofisica temporal
            # --------------------------------------------------------------------------------------------------------------
            PathTable = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '_Execution_SDR' + '.csv')
            Table.to_csv(PathTable, index=False)

            # Create args
            args = Create_argsInVEST(ProjectPath, UserData, Params, StatusK='SDR')

            # LULC
            args['lulc_path']           = NL
            args['lulc_raster_path']    = NL
            args['lulc_cur_path']       = NL

            # Biophysical Table Path
            args['biophysical_table_path']  = PathTable

            # Project Path
            args['workspace_dir']           = os.path.join(ProjectPath, 'OUTPUTS', '03-SDR', LULC) if BatchMode else os.path.join(ProjectPath, 'OUTPUTS', '03-SDR')
            args['results_suffix']          = LULC if BatchMode else UserData['Suffix']

            # Run SDR
            sdr.execute(args)

            # Model
            NameModel = NameModel + '| SDR |'

        # Nutrient Delivery Ratio
        if (UserData['Status_NDR_N'] == 1):
            print('----------------------------')
            print('Run NDR_N')
            print('----------------------------')

            # Aplicar factores a la tabla biofisica
            Table = Factor_BioTable(PathBioTable, Params, UserData)

            # --------------------------------------------------------------------------------------------------------------
            # Guardar Table Biofisica temporal
            # --------------------------------------------------------------------------------------------------------------
            PathTable = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '_Execution_NDR_N' + '.csv')
            Table.to_csv(PathTable, index=False)

            # Create args
            args = Create_argsInVEST(ProjectPath, UserData, Params, StatusK='NDR_N')

            # LULC
            args['lulc_path']           = NL
            args['lulc_raster_path']    = NL
            args['lulc_cur_path']       = NL

            # Biophysical Table Path
            args['biophysical_table_path']  = PathTable

            # Project Path
            args['workspace_dir']           = os.path.join(ProjectPath, 'OUTPUTS', '04-NDR_N', LULC) if BatchMode else os.path.join(ProjectPath, 'OUTPUTS', '04-NDR_N')
            args['results_suffix']          = LULC if BatchMode else UserData['Suffix']

            # run NDR
            ndr.execute(args)

            # Zonal nitgrogen
            raster_path = os.path.join(args['workspace_dir'], 'n_total_export_' + args['results_suffix'] + '.tif')
            Watershed   = os.path.join(ProjectPath, 'INPUTS',  'Basin', UserData['Basin'] + '.shp')
            output_path = args['workspace_dir']
            calculate_zonal_stats(Watershed, raster_path, output_path, Suffix=LULC + "_NDR_N")

            NameModel = NameModel + '| NDR_N |'

        # Nutrient Delivery Ratio
        if (UserData['Status_NDR_P'] == 1):
            print('----------------------------')
            print('Run NDR_P')
            print('----------------------------')

            # Aplicar factores a la tabla biofisica
            Table = Factor_BioTable(PathBioTable, Params, UserData)

            # --------------------------------------------------------------------------------------------------------------
            # Guardar Table Biofisica temporal
            # --------------------------------------------------------------------------------------------------------------
            PathTable = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '_Execution_NDR_P' + '.csv')
            Table.to_csv(PathTable, index=False)

            # Create args
            args = Create_argsInVEST(ProjectPath, UserData, Params, StatusK='NDR_P')

            # LULC
            args['lulc_path']           = NL
            args['lulc_raster_path']    = NL
            args['lulc_cur_path']       = NL

            # Biophysical Table Path
            args['biophysical_table_path']  = PathTable

            # Project Path
            args['workspace_dir']           = os.path.join(ProjectPath, 'OUTPUTS', '04-NDR_P', LULC) if BatchMode else os.path.join(ProjectPath, 'OUTPUTS', '04-NDR_P')
            args['results_suffix']          = LULC if BatchMode else UserData['Suffix']

            # run NDR
            ndr.execute(args)

            # zonal Phosphorus
            raster_path = os.path.join(args['workspace_dir'],'p_surface_export_' + args['results_suffix'] + '.tif')
            Watershed   = os.path.join(ProjectPath, 'INPUTS', 'Basin', UserData['Basin'] + '.shp')
            output_path = args['workspace_dir']
            calculate_zonal_stats(Watershed, raster_path, output_path, Suffix=LULC + "_NDR_P")

            NameModel = NameModel + '| NDR_P |'

        """
        # Carbons
        if UserData['Status_CO2'] == 1:
            print('----------------------------')
            print('Run CO2')
            print('----------------------------')

            # Aplicar factores a la tabla biofisica
            Table = Factor_BioTable(PathBioTable, Params, UserData)

            # --------------------------------------------------------------------------------------------------------------
            # Guardar Table Biofisica temporal
            # --------------------------------------------------------------------------------------------------------------
            PathTable = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '_Execution_CO2' + '.csv')
            Table.to_csv(PathTable, index=False)

            # Create args
            args                        = Create_argsInVEST(ProjectPath, UserData, Params, StatusK="CO2")

            # LULC
            args['lulc_path']           = NL
            args['lulc_raster_path']    = NL
            args['lulc_cur_path']       = NL

            # Biophysical Table Path
            args['carbon_pools_path']   = PathTable

            # Project Path
            args['workspace_dir']       = os.path.join(ProjectPath, 'OUTPUTS', '05-CO2')

            # Run CO2
            carbon.execute(args)

            # zonal Phosphorus
            raster_path = os.path.join(ProjectPath, 'OUTPUTS', '05-CO2','tot_c_cur_' + UserData['Suffix'] + '.tif')
            Watershed   = os.path.join(ProjectPath, 'INPUTS', 'Basin', UserData['Basin'] + '.shp')
            output_path = os.path.join(ProjectPath, 'OUTPUTS', '05-CO2')
            calculate_zonal_stats(Watershed, raster_path, output_path, Suffix=LULC + "_CO2")

            NameModel = NameModel + '| CO2 |'
        """

        # --------------------------------------------------------------------------------------------------------------
        # Guardar Table Biofisica final
        # --------------------------------------------------------------------------------------------------------------
        # Aplicar factores a la tabla biofisica
        Table = Factor_BioTable(PathBioTable, Params, UserData)
        PathTable = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '_Execution_Total.csv')
        Table.to_csv(PathTable, index=False)

        print('#################################################')
        print('   //////////   ')
        print('   |        |   ')
        print('  _|  _   _ |_  ')
        print(' |.|-(.)-(.)+.| ')
        print('  \\|    J   |/  ')
        print('   \\   ---  /   ')
        print('    \\      /    ')
        print('     "####"     ')
        print('successful execution - ' + NameModel + ' LULC: ' + LULC)
        print('#################################################')

def Read_Inputs_InVEST(InVEST_Main_Path):
    # ----------------------------------------------------------------------------------------------------------------------
    # Input Data for InVEST models
    # ----------------------------------------------------------------------------------------------------------------------
    Tmp = pd.read_excel(InVEST_Main_Path,sheet_name='UserData',index_col=0)
    UserData = {}
    UserData['Pixel']           = Tmp.loc['Pixel', 'Value']
    UserData['Suffix']          = Tmp.loc['Name', 'Value']
    UserData['BioTable']        = Tmp.loc['BioTable', 'Value']
    UserData['RainTable']       = Tmp.loc['RainTable', 'Value']
    UserData['LULC']            = Tmp.loc['LULC', 'Value']
    UserData['DEM']             = Tmp.loc['DEM', 'Value']
    UserData['R']               = Tmp.loc['R', 'Value']
    UserData['K']               = Tmp.loc['K', 'Value']
    UserData['SoilDepth']       = Tmp.loc['SoilDepth', 'Value']
    UserData['ETP']             = Tmp.loc['ETP', 'Value']
    UserData['ETP_Path']        = Tmp.loc['ETP_M', 'Value']
    UserData['P']               = Tmp.loc['P', 'Value']
    UserData['P_Path']          = Tmp.loc['P_M', 'Value']
    UserData['PAWC']            = Tmp.loc['PAWC', 'Value']
    UserData['SoilGroup']       = Tmp.loc['HSG', 'Value']
    UserData['Stream']          = Tmp.loc['Stream', 'Value']
    UserData['Basin']           = Tmp.loc['Basin', 'Value']
    UserData['SubBasin']        = Tmp.loc['SubBasin', 'Value']
    UserData['Threshold']       = Tmp.loc['Threshold_Flow', 'Value']
    UserData['Status_AWY']      = Tmp.loc['Run', 'AWY']
    UserData['Status_SWY']      = Tmp.loc['Run', 'SWY']
    UserData['Status_SDR']      = Tmp.loc['Run', 'SDR']
    UserData['Status_NDR_N']    = Tmp.loc['Run', 'NDR_N']
    UserData['Status_NDR_P']    = Tmp.loc['Run', 'NDR_P']
    #UserData['Status_CO2']      = Tmp.loc['Run', 'CO2']

    return UserData

def Read_Parameters_InVEST(InVEST_Main_Path):

    # ----------------------------------------------------------------------------------------------------------------------
    # Parameters
    # ----------------------------------------------------------------------------------------------------------------------
    Tmp = pd.read_excel(InVEST_Main_Path, sheet_name='Params', index_col=0)
    Params = {}
    Params['Z']                 = Tmp.loc['Z', 'Value']
    Params['Factor-Kc']         = Tmp.loc['Factor-Kc', 'Value']
    Params['Factor-Kc_m']       = Tmp.loc['Factor-Kc_m', 'Value']
    Params['Gamma']             = Tmp.loc['Gamma', 'Value']
    Params['Beta']              = Tmp.loc['Beta', 'Value']
    Params['Alpha']             = Tmp.loc['Alpha', 'Value']
    Params['Factor-C']          = Tmp.loc['Factor-C', 'Value']
    Params['Factor-P']          = Tmp.loc['Factor-P', 'Value']
    Params['IC0']               = Tmp.loc['Borselli-IC0', 'Value']
    Params['L_max']             = Tmp.loc['L_max', 'Value']
    Params['sdr_max']           = Tmp.loc['sdr_max', 'Value']
    Params['Factor_Load_N']     = Tmp.loc['Factor_Load_N', 'Value']
    Params['Factor_Eff_N']      = Tmp.loc['Factor_Eff_N', 'Value']
    Params['SubCri_Len_N']      = Tmp.loc['SubCri_Len_N', 'Value']
    Params['Sub_Eff_N']         = Tmp.loc['Sub_Eff_N', 'Value']
    Params['Factor_Load_P']     = Tmp.loc['Factor_Load_P', 'Value']
    Params['Factor_Eff_P']      = Tmp.loc['Factor_Eff_P', 'Value']
    Params['Borselli-K_SDR']    = Tmp.loc['Borselli-K_SDR', 'Value']
    Params['Borselli-K_NDR']    = Tmp.loc['Borselli-K_NDR', 'Value']

    return Params

def Read_ParameterRange_InVEST(InVEST_Main_Path):
    
    # ----------------------------------------------------------------------------------------------------------------------
    # Parameters range
    # ----------------------------------------------------------------------------------------------------------------------
    Tmp = pd.read_excel(InVEST_Main_Path,sheet_name='Params',index_col=0)

    # Minimum values
    ParamsMin = {}
    ParamsMin['Z']              = Tmp.loc['Z', 'Min']
    ParamsMin['Factor-Kc']      = Tmp.loc['Factor-Kc', 'Min']
    ParamsMin['Factor-Kc_m']    = Tmp.loc['Factor-Kc_m', 'Min']
    ParamsMin['Gamma']          = Tmp.loc['Gamma', 'Min']
    ParamsMin['Beta']           = Tmp.loc['Beta', 'Min']
    ParamsMin['Alpha']          = Tmp.loc['Alpha', 'Min']
    ParamsMin['Factor-C']       = Tmp.loc['Factor-C', 'Min']
    ParamsMin['Factor-P']       = Tmp.loc['Factor-P', 'Min']
    ParamsMin['IC0']            = Tmp.loc['Borselli-IC0', 'Min']
    ParamsMin['L_max']          = Tmp.loc['L_max', 'Min']
    ParamsMin['sdr_max']        = Tmp.loc['sdr_max', 'Min']
    ParamsMin['Factor_Load_N']  = Tmp.loc['Factor_Load_N', 'Min']
    ParamsMin['Factor_Eff_N']   = Tmp.loc['Factor_Eff_N', 'Min']
    ParamsMin['SubCri_Len_N']   = Tmp.loc['SubCri_Len_N', 'Min']
    ParamsMin['Sub_Eff_N']      = Tmp.loc['Sub_Eff_N', 'Min']
    ParamsMin['Factor_Load_P']  = Tmp.loc['Factor_Load_P', 'Min']
    ParamsMin['Factor_Eff_P']   = Tmp.loc['Factor_Eff_P', 'Min']
    ParamsMin['Borselli-K_SDR'] = Tmp.loc['Borselli-K_SDR', 'Min']
    ParamsMin['Borselli-K_NDR'] = Tmp.loc['Borselli-K_NDR', 'Min']

    # Maximum values
    ParamsMax = {}
    ParamsMax['Z']              = Tmp.loc['Z', 'Max']
    ParamsMax['Factor-Kc']      = Tmp.loc['Factor-Kc', 'Max']
    ParamsMax['Factor-Kc_m']    = Tmp.loc['Factor-Kc_m', 'Max']
    ParamsMax['Gamma']          = Tmp.loc['Gamma', 'Max']
    ParamsMax['Beta']           = Tmp.loc['Beta', 'Max']
    ParamsMax['Alpha']          = Tmp.loc['Alpha', 'Max']
    ParamsMax['Factor-C']       = Tmp.loc['Factor-C', 'Max']
    ParamsMax['Factor-P']       = Tmp.loc['Factor-P', 'Max']
    ParamsMax['IC0']            = Tmp.loc['Borselli-IC0', 'Max']
    ParamsMax['L_max']          = Tmp.loc['L_max', 'Max']
    ParamsMax['sdr_max']        = Tmp.loc['sdr_max', 'Max']
    ParamsMax['Factor_Load_N']  = Tmp.loc['Factor_Load_N', 'Max']
    ParamsMax['Factor_Eff_N']   = Tmp.loc['Factor_Eff_N', 'Max']
    ParamsMax['SubCri_Len_N']   = Tmp.loc['SubCri_Len_N', 'Max']
    ParamsMax['Sub_Eff_N']      = Tmp.loc['Sub_Eff_N', 'Max']
    ParamsMax['Factor_Load_P']  = Tmp.loc['Factor_Load_P', 'Max']
    ParamsMax['Factor_Eff_P']   = Tmp.loc['Factor_Eff_P', 'Max']
    ParamsMax['Borselli-K_SDR'] = Tmp.loc['Borselli-K_SDR', 'Max']
    ParamsMax['Borselli-K_NDR'] = Tmp.loc['Borselli-K_NDR', 'Max']

    return ParamsMin, ParamsMax

# ----------------------------------------------------------------------------------------------------------------------
# Inicialización de archivos temporales para calibración metricas
# ----------------------------------------------------------------------------------------------------------------------
class Spotpy_InVEST(object):
    def __init__(self,ProjectPath, InVEST_Main_Path, NameModel, NameFunObj, FactorMetric):
        # Create Paths
        CreateFolder(os.path.join(ProjectPath, 'EVALUATIONS'))
        CreateFolder(os.path.join(ProjectPath, 'PARAMETERS'))
        CreateFolder(os.path.join(ProjectPath, 'OUTPUTS'))
        CreateFolder(os.path.join(ProjectPath, 'FIGURES'))
        CreateFolder(os.path.join(ProjectPath, 'TMP'))
        
        # Read UserData
        UserData = Read_Inputs_InVEST(InVEST_Main_Path)

        # Read Parameter Range Model
        ParamsMin, ParamsMax = Read_ParameterRange_InVEST(InVEST_Main_Path)

        # Parameters - Annual Water Yield (AWY)
        if NameModel == 'AWY':
            # Parameters
            self.params = [spotpy.parameter.Uniform('Z',            ParamsMin['Z'],             ParamsMax['Z']),
                           spotpy.parameter.Uniform('Factor-Kc',    ParamsMin['Factor-Kc'],     ParamsMax['Factor-Kc'])
                           ]

        # Parameters - Seasonal Water Yield (AWY)
        if NameModel == 'SWY':
            # Parameters
            self.params = [spotpy.parameter.Uniform('Gamma',        ParamsMin['Gamma'],         ParamsMax['Gamma']),
                           spotpy.parameter.Uniform('Beta',         ParamsMin['Beta'],          ParamsMax['Beta']),
                           spotpy.parameter.Uniform('Alpha',        ParamsMin['Alpha'],         ParamsMax['Alpha']),
                           spotpy.parameter.Uniform('Factor-Kc',    ParamsMin['Factor-Kc_m'],   ParamsMax['Factor-Kc_m'])
                           ]

        # Parameters - Sediment Delivery Ratio (SDR)
        elif NameModel == 'SDR':
            self.params = [spotpy.parameter.Uniform('sdr_max',      ParamsMin['sdr_max'],       ParamsMax['sdr_max']),
                           spotpy.parameter.Uniform('Borselli_K',   ParamsMin['Borselli-K_SDR'],ParamsMax['Borselli-K_SDR']),
                           spotpy.parameter.Uniform('ic_0_param',   ParamsMin['IC0'],           ParamsMax['IC0']),
                           spotpy.parameter.Uniform('l_max',        ParamsMin['L_max'],         ParamsMax['L_max']),
                           spotpy.parameter.Uniform('Factor-C',     ParamsMin['Factor-C'],      ParamsMax['Factor-C']),
                           spotpy.parameter.Uniform('Factor-P',     ParamsMin['Factor-P'],      ParamsMax['Factor-P']),
                           ]

        # Parameters - Nutrient Delivery Ratio - Nitrogen (NDR)
        elif NameModel == 'NDR_N':
            self.params = [spotpy.parameter.Uniform('SubCri_Len_N', ParamsMin['SubCri_Len_N'],  ParamsMax['SubCri_Len_N']),
                           spotpy.parameter.Uniform('Sub_Eff_N',    ParamsMin['Sub_Eff_N'],     ParamsMax['Sub_Eff_N']),
                           spotpy.parameter.Uniform('Borselli_K',   ParamsMin['Borselli-K_NDR'],ParamsMax['Borselli-K_NDR']),
                           spotpy.parameter.Uniform('Factor_Load_N',ParamsMin['Factor_Load_N'], ParamsMax['Factor_Load_N']),
                           spotpy.parameter.Uniform('Factor_Eff_N', ParamsMin['Factor_Eff_N'],  ParamsMax['Factor_Eff_N']),
                           ]

        # Parameters - Nutrient Delivery Ratio - Phosphorus (NDR)
        elif NameModel == 'NDR_P':
            self.params = [spotpy.parameter.Uniform('Borselli_K',   ParamsMin['Borselli-K_NDR'],ParamsMax['Borselli-K_NDR']),
                           spotpy.parameter.Uniform('Factor_Load_P',ParamsMin['Factor_Load_P'], ParamsMax['Factor_Load_P']),
                           spotpy.parameter.Uniform('Factor_Eff_P', ParamsMin['Factor_Eff_P'],  ParamsMax['Factor_Eff_P']),

                           ]

        # Project Path
        self.ProjectPath    = ProjectPath
        # UserData
        self.UserData       = UserData
        # Name Model
        self.NameModel      = NameModel
        # Name Function Object
        self.NameFunObj     = NameFunObj
        # Factor Metric
        self.FactorMetric   = FactorMetric
        # Datos observados
        self.Obs            = pd.read_excel(InVEST_Main_Path, sheet_name='Obs_Data')

    def parameters(self):
        return spotpy.parameter.generate(self.params)

    def simulation(self, vector):
        return np.array(vector)

    def evaluation(self):
        return self.Obs

    def objectivefunction(self, simulation, evaluation):

        # Name Model
        NameModel = self.NameModel
        
        # Annual Water Yield (AWY)    
        if NameModel == 'AWY':
            return Execute_AWY(self.ProjectPath, self.UserData, simulation, evaluation, self.NameFunObj, self.FactorMetric)
        # Seasonal Water Yield (AWY)
        if NameModel == 'SWY':
            return Execute_SWY(self.ProjectPath, self.UserData, simulation, evaluation, self.NameFunObj, self.FactorMetric)
        # Sediment Delivery Ratio (SDR)
        elif NameModel == 'SDR':
            return Execute_SDR(self.ProjectPath, self.UserData, simulation, evaluation, self.NameFunObj, self.FactorMetric)
        # Nutrient Delivery Ratio - Nitrogen (NDR)
        elif NameModel == 'NDR_N':
            return Execute_NDR_N(self.ProjectPath, self.UserData, simulation, evaluation, self.NameFunObj, self.FactorMetric)
        # Nutrient Delivery Ratio - Phosphorus (NDR)
        elif NameModel == 'NDR_P':
            return Execute_NDR_P(self.ProjectPath, self.UserData, simulation, evaluation, self.NameFunObj, self.FactorMetric)

def Cal_FunObj(Obs, Sim, NameFunObj):

    if NameFunObj == "Mean Square Error (MSE)":
        return spotpy.objectivefunctions.mse(Obs, Sim)
    elif NameFunObj == "Mean Absolute Error (MAE)":
        return spotpy.objectivefunctions.mae(Obs, Sim)
    elif NameFunObj == "Root Mean Square Error (RMSE)":
        return spotpy.objectivefunctions.rmse(Obs, Sim)
    elif NameFunObj == "Relative Root Mean Squared Error (RRMSE)":
        return spotpy.objectivefunctions.rrmse(Obs, Sim)

def Execute_AWY(ProjectPath, UserData, simulation, evaluation, NameFunObj, FactorMetric):

    # Parameters
    x = simulation

    # --------------------------------------------------------------------------------------------------------------
    # Print
    # --------------------------------------------------------------------------------------------------------------
    print('----------------------------------------')
    print('Parameters - AWY')
    print('----------------------------------------')
    print('Z         = ' + '%.2f' % x[0])
    print('Factor-Kc = ' + '%.2f' % x[1])
    print('----------------------------------------')

    # --------------------------------------------------------------------------------------------------------------
    # Configuración de diccionario de entrada del modelo
    # --------------------------------------------------------------------------------------------------------------
    Params          = {'Z': x[0],'Factor-Kc':x[1]}
    # Aplicar factores a la tabla biofísica y guardar
    PathBioTable    = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '.csv')
    Table           = Factor_BioTable(PathBioTable, Params, UserData)
    PathTable       = os.path.join(ProjectPath, 'TMP', 'AWY_' + UserData['BioTable'] + '.csv')
    Table.to_csv(PathTable, index=False)
    # Configuración de diccionario de entrada del modelo
    args    = Create_argsInVEST(ProjectPath, UserData, Params, StatusK="AWY")
    # Ruta de la tabla biofisica temporal de la region
    args['biophysical_table_path']  = PathTable
    # Ruta de la cuenca de la Region
    args['watersheds_path']         = os.path.join(ProjectPath, 'INPUTS', 'Basin_Cal_AWY', 'Basin_Cal_AWY.shp')
    # Ruta de la carpeta de resultados de la region
    args['workspace_dir']           = os.path.join(ProjectPath, 'OUTPUTS', '01-AWY')

    # --------------------------------------------------------------------------------------------------------------
    # Ejecución del modelo
    # --------------------------------------------------------------------------------------------------------------
    awy.execute(args)

    # --------------------------------------------------------------------------------------------------------------
    # Lectura del csv de resultados
    # --------------------------------------------------------------------------------------------------------------
    NameFile    = os.path.join(args['workspace_dir'], 'output', 'watershed_results_wyield_' + UserData['Suffix'] + '.csv')
    simulation  = pd.read_csv(NameFile)
    Sim         = simulation['wyield_vol'].values

    # --------------------------------------------------------------------------------------------------------------
    # Busca los datos de rendimiento hidrico en la tabla de resultados asociados a cada cuenca
    # --------------------------------------------------------------------------------------------------------------
    [I, idx]    = ismember(simulation['ws_id'].values, evaluation['ws_id'].values)
    Obs         = evaluation['AWY'].values[idx]
    #Sim         = Sim[I]

    # --------------------------------------------------------------------------------------------------------------
    # Calcula la metrica
    # --------------------------------------------------------------------------------------------------------------
    objectivefunction = FactorMetric*Cal_FunObj(Obs, Sim, NameFunObj)

    # --------------------------------------------------------------------------------------------------------------
    # Guarda el valor de la metrica en el CSV Metric
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'AWY_Metric_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('Z,Factor-Kc,' + NameFunObj + '\n')

        ID_File.write('%0.2f' % x[0] + ',' +
                      '%0.2f' % x[1] + ',' +
                      '%0.2f' % objectivefunction + '\n')

    # --------------------------------------------------------------------------------------------------------------
    # Guarda el valor observado en el CSV Obs
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'AWY_Obs_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('Obs\n')

        for ii in range(0, len(Obs)):
            ID_File.write('%0.2f' % Obs[ii] + '\n')

    # --------------------------------------------------------------------------------------------------------------
    # Guarda la simulacion en el archivo CSV Sim
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'AWY_Sim_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('Sim\n')

        for ii in range(0, len(Sim)):
            ID_File.write('%0.2f' % Sim[ii] + '\n')

    return objectivefunction

def Execute_SWY(ProjectPath, UserData, simulation, evaluation, NameFunObj, FactorMetric):
    # ---------------------------------------------------------------------
    # Parameters
    # ---------------------------------------------------------------------
    x = simulation

    # ---------------------------------------------------------------------
    # Print
    # ---------------------------------------------------------------------
    print('---------------------------')
    print('Alpha = ' + '%.3f' % x[0])
    print('Beta  = ' + '%.3f' % x[1])
    print('Gamma = ' + '%.3f' % x[2])
    print('Factor-Kc = ' + '%.2f' % x[3])

    # --------------------------------------------------------------------------------------------------------------
    # Configuración de diccionario de entrada del modelo
    # --------------------------------------------------------------------------------------------------------------
    Params          = {'Alpha':x[0],'Beta':x[1],'Gamma':x[2],'Factor-Kc_m':x[3]}
    # Aplicar factores a la tabla biofísica y guardar
    PathBioTable    = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '.csv')
    Table           = Factor_BioTable(PathBioTable, Params, UserData)
    PathTable       = os.path.join(ProjectPath, 'TMP', 'SWY_' + UserData['BioTable'] + '.csv')
    Table.to_csv(PathTable, index=False)
    # Configuración de diccionario de entrada del modelo
    args    = Create_argsInVEST(ProjectPath, UserData, Params, StatusK="SWY")
    # Ruta de la tabla biofisica temporal de la region
    args['biophysical_table_path']  = PathTable
    # Ruta de la cuenca de la Region
    args['watersheds_path']         = os.path.join(ProjectPath, 'INPUTS', 'Basin_Cal_SWY', 'Basin_Cal_SWY.shp')
    # Ruta de la carpeta de resultados de la region
    args['workspace_dir']           = os.path.join(ProjectPath, 'OUTPUTS', '02-SWY')

    # Run
    swy.execute(args)

    # read Results
    raster_path = os.path.join(args['workspace_dir'], 'intermediate_outputs','aet_' + UserData['Suffix'] + '.tif')
    output_path = os.path.join(ProjectPath, 'TMP')
    simulation  = calculate_zonal_stats(args['watersheds_path'], raster_path, output_path,Suffix="SWY")
    Sim         = simulation['mean'].values

    # --------------------------------------------------------------------------------------------------------------
    # Busca los datos de rendimiento hidrico en la tabla de resultados asociados a cada cuenca
    # --------------------------------------------------------------------------------------------------------------
    [I, idx] = ismember(simulation['ws_id'].values, evaluation['ws_id'].values)
    Obs = evaluation['SWY'].values[idx]
    Sim = Sim[I]

    # --------------------------------------------------------------------------------------------------------------
    # Calcula la metrica
    # --------------------------------------------------------------------------------------------------------------
    objectivefunction = FactorMetric*Cal_FunObj(Obs, Sim, NameFunObj)

    # --------------------------------------------------------------------------------------------------------------
    # Guarda el valor de la metrica en el CSV Metric
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'SWY_Metric_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('Alpha,Beta,Gamma,Factor-Kc,' + NameFunObj + '\n')

        ID_File.write('%0.3f' % x[0] + ',' +
                      '%0.3f' % x[1] + ',' +
                      '%0.3f' % x[2] + ',' +
                      '%0.2f' % x[3] + ',' +
                      '%0.2f' % objectivefunction + '\n')

    # --------------------------------------------------------------------------------------------------------------
    # Guarda el valor observado en el CSV Obs
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'SWY_Obs_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('Obs\n')

        for ii in range(0, len(Obs)):
            ID_File.write('%0.2f' % Obs[ii] + '\n')

    # --------------------------------------------------------------------------------------------------------------
    # Guarda la simulacion en el archivo CSV Sim
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'SWY_Sim_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('Sim\n')

        for ii in range(0, len(Sim)):
            ID_File.write('%0.2f' % Sim[ii] + '\n')

    return objectivefunction

def Execute_SDR(ProjectPath, UserData, simulation, evaluation, NameFunObj, FactorMetric):

    # Parameters
    x = simulation

    # ---------------------------------------------------------------------
    # Print
    # ---------------------------------------------------------------------
    print('---------------------------')
    print('sdr_max  = ' + '%.2f' % x[0])
    print('K        = ' + '%.2f' % x[1])
    print('IC0      = ' + '%.2f' % x[2])
    print('l_max    = ' + '%.2f' % x[3])
    print('Factor-C = ' + '%.2f' % x[4])
    print('Factor-P = ' + '%.2f' % x[5])

    # --------------------------------------------------------------------------------------------------------------
    # Configuración de diccionario de entrada del modelo
    # --------------------------------------------------------------------------------------------------------------
    Params  = {'sdr_max':x[0],'Borselli-K_SDR':x[1],'IC0':x[2],'L_max':x[3],'Factor-C':x[4],'Factor-P':x[5]}
    # Aplicar factores a la tabla biofísica y guardar
    PathBioTable    = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '.csv')
    Table           = Factor_BioTable(PathBioTable, Params, UserData)
    PathTable       = os.path.join(ProjectPath, 'TMP', 'SDR_' + UserData['BioTable'] + '.csv')
    Table.to_csv(PathTable, index=False)
    # Configuración de diccionario de entrada del modelo
    args    = Create_argsInVEST(ProjectPath, UserData, Params,StatusK='SDR')
    # Ruta de la tabla biofisica temporal de la region
    args['biophysical_table_path']  = PathTable
    # Ruta de la cuenca de la Region
    args['watersheds_path']         = os.path.join(ProjectPath, 'INPUTS', 'Basin_Cal_SDR', 'Basin_Cal_SDR.shp')
    # Ruta de la carpeta de resultados de la region
    args['workspace_dir']           = os.path.join(ProjectPath, 'OUTPUTS', '03-SDR')
    # Metodo direcciones de flujo
    args['flow_dir_algorithm']      = 'MFD'

    # ---------------------------------------------------------------------
    # Ejecucion del modelo
    # ---------------------------------------------------------------------
    sdr.execute(args)

    # ---------------------------------------------------------------------
    # Lectura del dbf de resultados
    # ---------------------------------------------------------------------
    NameFile    = os.path.join( args['workspace_dir'] , 'watershed_results_sdr_' + UserData['Suffix'] + '.dbf')
    dbf         = Dbf5(NameFile)
    simulation  = dbf.to_dataframe()

    # ---------------------------------------------------------------------
    # Busca los datos de carga de sedimentos en la tabla de resultados asociados a cada cuenca
    # ---------------------------------------------------------------------
    Sim         = simulation['sed_export'].values
    [I, idx]    = ismember(simulation['ws_id'].values, evaluation['ws_id'].values)
    Obs         = evaluation['SDR'].values[idx]
    Sim         = Sim[I]

    # --------------------------------------------------------------------------------------------------------------
    # Calcula la metrica
    # --------------------------------------------------------------------------------------------------------------
    objectivefunction = FactorMetric*Cal_FunObj(Obs, Sim, NameFunObj)

    # --------------------------------------------------------------------------------------------------------------
    # Guarda el valor de la metrica en el CSV Metric
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'SDR_Metric_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('sdr_max,k_param,ic_0_param,l_max,Factor-C,Factor-P,' + NameFunObj + '\n')

        ID_File.write('%0.2f' % x[0] + ',' +
                      '%0.2f' % x[1] + ',' +
                      '%0.2f' % x[2] + ',' +
                      '%0.2f' % x[3] + ',' +
                      '%0.5f' % x[4] + ',' +
                      '%0.5f' % x[5] + ',' +
                      '%0.2f' % objectivefunction + '\n')

    # --------------------------------------------------------------------------------------------------------------
    # Guarda el valor observado en el CSV Obs
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'SDR_Obs_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('Obs\n')

        for ii in range(0, len(Obs)):
            ID_File.write('%0.2f' % Obs[ii] + '\n')

    # --------------------------------------------------------------------------------------------------------------
    # Guarda la simulacion en el archivo CSV Sim
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'SDR_Sim_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('Sim\n')

        for ii in range(0, len(Sim)):
            ID_File.write('%0.2f' % Sim[ii] + '\n')

    return objectivefunction

def Execute_NDR_N(ProjectPath, UserData, simulation, evaluation, NameFunObj, FactorMetric):
    # Parameters
    x = simulation

    # --------------------------------------------------------------------------------------------------------------
    # Print
    # --------------------------------------------------------------------------------------------------------------
    print('---------------------------------')
    print('SubCri_Len_N   = ' + '%.2f' % x[0])
    print('Sub_Eff_N      = ' + '%.2f' % x[1])
    print('Borselli-K     = ' + '%.2f' % x[2])
    print('Factor_Load_N  = ' + '%.2f' % x[3])
    print('Factor_Eff_N   = ' + '%.2f' % x[4])

    # --------------------------------------------------------------------------------------------------------------
    # Configuración de diccionario de entrada del modelo
    # --------------------------------------------------------------------------------------------------------------
    Params  = {'SubCri_Len_N':x[0],'Sub_Eff_N':x[1],'Borselli-K_NDR':x[2],'Factor_Load_N':x[3],'Factor_Eff_N':x[4]}
    # Aplicar factores a la tabla biofísica y guardar
    PathBioTable    = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '.csv')
    Table           = Factor_BioTable(PathBioTable, Params, UserData)
    PathTable       = os.path.join(ProjectPath, 'TMP', 'NDR_N_' + UserData['BioTable'] + '.csv')
    Table.to_csv(PathTable, index=False)
    # Configuración de diccionario de entrada del modelo
    args    = Create_argsInVEST(ProjectPath, UserData, Params, StatusK='NDR_N')
    # Ruta de la tabla biofisica temporal de la region
    args['biophysical_table_path']  = PathTable
    # Ruta de la cuenca de la Region
    args['watersheds_path']         = os.path.join(ProjectPath, 'INPUTS', 'Basin_Cal_NDR_N','Basin_Cal_NDR_N.shp')
    # Ruta de la carpeta de resultados de la region
    args['workspace_dir']           = os.path.join(ProjectPath, 'OUTPUTS', '04-NDR_N')
    # Metodo de direcciones de flujo
    args['flow_dir_algorithm']      = 'MFD'

    # --------------------------------------------------------------------------------------------------------------
    # Ejecucion del modelo de nutrientes
    # --------------------------------------------------------------------------------------------------------------
    ndr.execute(args)

    # --------------------------------------------------------------------------------------------------------------
    # Lectura del dbf de resultados
    # --------------------------------------------------------------------------------------------------------------
    raster_path = os.path.join(args['workspace_dir'], 'n_total_export_' + UserData['Suffix'] + '.tif')
    output_path = os.path.join(ProjectPath, 'TMP')
    simulation  = calculate_zonal_stats(args['watersheds_path'], raster_path, output_path,Suffix="NDR_N")
    Sim         = simulation['sum'].values

    # --------------------------------------------------------------------------------------------------------------
    # Busca los datos de carga de nitrogeno en la tabla de resultados asociados a cada cuenca
    # --------------------------------------------------------------------------------------------------------------
    [I, idx]    = ismember(simulation['ws_id'].values, evaluation['ws_id'].values)
    Obs         = evaluation['NDR_N'].values[idx]
    Sim         = Sim[I]

    # --------------------------------------------------------------------------------------------------------------
    # Calcula la metrica
    # --------------------------------------------------------------------------------------------------------------
    objectivefunction = FactorMetric*Cal_FunObj(Obs, Sim, NameFunObj)

    # --------------------------------------------------------------------------------------------------------------
    # Guarda el valor de la metrica en el CSV Metric
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'NDR_N_Metric_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('SubCri_Len_N,Sub_Eff_N,Borselli-K,Factor_Load_N,Factor_Eff_N,' + NameFunObj + '\n')

        ID_File.write('%0.2f' % x[0] + ',' +
                      '%0.2f' % x[1] + ',' +
                      '%0.2f' % x[2] + ',' +
                      '%0.2f' % x[3] + ',' +
                      '%0.5f' % x[4] + ',' +
                      '%0.2f' % objectivefunction + '\n')

    # --------------------------------------------------------------------------------------------------------------
    # Guarda el valor observado en el CSV Obs
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'NDR_N_Obs_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('Obs\n')

        for ii in range(0, len(Obs)):
            ID_File.write('%0.2f' % Obs[ii] + '\n')

    # --------------------------------------------------------------------------------------------------------------
    # Guarda la simulacion en el archivo CSV Sim
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'NDR_N_Sim_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('Sim\n')

        for ii in range(0, len(Sim)):
            ID_File.write('%0.2f' % Sim[ii] + '\n')

    # --------------------------------------------------------------------------------------------------------------
    # Salida de la funcion
    # --------------------------------------------------------------------------------------------------------------
    return objectivefunction

def Execute_NDR_P(ProjectPath, UserData, simulation, evaluation, NameFunObj, FactorMetric):
    # Parameters
    x = simulation.tolist()

    # --------------------------------------------------------------------------------------------------------------
    # Print
    # --------------------------------------------------------------------------------------------------------------
    print('------------------------------')
    print('Borselli-K     = ' + '%.2f' % x[0])
    print('Factor_Load_P  = ' + '%.2f' % x[1])
    print('Factor_Eff_P   = ' + '%.2f' % x[2])

    # --------------------------------------------------------------------------------------------------------------
    # Configuración de diccionario de entrada del modelo
    # --------------------------------------------------------------------------------------------------------------
    Params  = {'Borselli-K_NDR':x[0],'Factor_Load_P':x[1],'Factor_Eff_P':x[2]}
    # Aplicar factores a la tabla biofísica y guardar
    PathBioTable    = os.path.join(ProjectPath, 'INPUTS', UserData['BioTable'] + '.csv')
    Table           = Factor_BioTable(PathBioTable, Params, UserData)
    PathTable       = os.path.join(ProjectPath, 'TMP', 'NDR_P_' + UserData['BioTable'] + '.csv')
    Table.to_csv(PathTable, index=False)
    # Configuración de diccionario de entrada del modelo
    args    = Create_argsInVEST(ProjectPath, UserData, Params, StatusK='NDR_P')
    # Ruta de la tabla biofisica temporal de la region
    args['biophysical_table_path']  = PathTable
    # Ruta de la cuenca de la Region
    args['watersheds_path']         = os.path.join(ProjectPath, 'INPUTS', 'Basin_Cal_NDR_P', 'Basin_Cal_NDR_P.shp')
    # Ruta de la carpeta de resultados de la region
    args['workspace_dir']           = os.path.join(ProjectPath, 'OUTPUTS', '04-NDR_P')
    # Metodo de direcciones de flujo
    args['flow_dir_algorithm']      = 'MFD'

    # --------------------------------------------------------------------------------------------------------------
    # Ejecucion del modelo de nutrientes
    # --------------------------------------------------------------------------------------------------------------
    ndr.execute(args)

    # --------------------------------------------------------------------------------------------------------------
    # Lectura del dbf de resultados
    # --------------------------------------------------------------------------------------------------------------
    raster_path = os.path.join(args['workspace_dir'], 'p_surface_export_' + UserData['Suffix'] + '.tif')
    output_path = os.path.join(ProjectPath, 'TMP')
    simulation  = calculate_zonal_stats(args['watersheds_path'], raster_path, output_path,Suffix="NDR_P")
    Sim         = simulation['sum'].values

    # --------------------------------------------------------------------------------------------------------------
    # Busca los datos de carga de nitrogeno en la tabla de resultados asociados a cada cuenca
    # --------------------------------------------------------------------------------------------------------------
    [I, idx]    = ismember(simulation['ws_id'].values, evaluation['ws_id'].values)
    Obs         = evaluation['NDR_P'].values[idx]
    Sim         = Sim[I]

    # --------------------------------------------------------------------------------------------------------------
    # Calcula la metrica
    # --------------------------------------------------------------------------------------------------------------
    objectivefunction = FactorMetric*Cal_FunObj(Obs, Sim, NameFunObj)

    # --------------------------------------------------------------------------------------------------------------
    # Guarda el valor de la metrica en el CSV Metric
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'NDR_P_Metric_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('Borselli-K,Factor_Load_P,Factor_Eff_P,' + NameFunObj + '\n')

        ID_File.write('%0.2f' % x[0] + ',' +
                      '%0.2f' % x[1] + ',' +
                      '%0.2f' % x[2] + ',' +
                      '%0.2f' % objectivefunction + '\n')

    # --------------------------------------------------------------------------------------------------------------
    # Guarda el valor observado en el CSV Obs
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'NDR_P_Obs_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('Obs\n')

        for ii in range(0, len(Obs)):
            ID_File.write('%0.2f' % Obs[ii] + '\n')

    # --------------------------------------------------------------------------------------------------------------
    # Guarda la simulacion en el archivo CSV Sim
    # --------------------------------------------------------------------------------------------------------------
    PathResults = os.path.join(ProjectPath, 'EVALUATIONS', 'NDR_P_Sim_' + UserData['Suffix'] + '.csv')
    file_exists = os.path.isfile(PathResults)
    with open(PathResults, 'a') as ID_File:
        if not file_exists:
            ID_File.write('Sim\n')

        for ii in range(0, len(Sim)):
            ID_File.write('%0.2f' % Sim[ii] + '\n')

    # --------------------------------------------------------------------------------------------------------------
    # Salida de la funcion
    # --------------------------------------------------------------------------------------------------------------
    return objectivefunction

def Plot_AWY(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):

    # Metric and parameters
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'AWY_Metric_{Suffix}.csv')
    Tmp         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Params      = Tmp[:, :2]
    Metric      = Tmp[:, 2] / (3600 * 24 * 365)

    # Observed
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'AWY_Obs_{Suffix}.csv')
    Obs         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    NGauges     = len(Obs) // len(Metric)
    Obs         = Obs.reshape(len(Metric),NGauges)
    Obs         = Obs.transpose()
    Obs         = Obs[:, 0] / (3600 * 24 * 365)
    Obs         = Obs.reshape(NGauges,1)

    # Simulation
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'AWY_Sim_{Suffix}.csv')
    Sim         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Sim         = Sim.reshape(len(Metric),len(Sim) // len(Metric))
    Sim         = Sim.transpose() / (3600 * 24 * 365)

    # Best Parameters
    id_min      = np.argmin(Metric)
    BestParams  = Params[id_min, :]
    BestAREM    = FactorMetric*Metric[id_min]
    Metric      = FactorMetric*Metric

    # Scatter Plot
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # Plot Obs Vs Sim
    ax = axes[0]
    max_val = max(np.max(Obs), np.max(Sim[:, id_min])) * 1.1
    ax.plot([0, max_val], [0, max_val], linewidth=1.2, color=[0.8, 0.8, 0.8])
    ax.scatter(Obs, Sim[:, id_min], s=100, edgecolor=[0, 0.5, 0.5], facecolor=[0, 0.7, 0.7],alpha=0.2, linewidth=1.2)
    ax.set_xlabel(r'Observed $(\mathrm{m}^3/\mathrm{s})$', fontsize=16)
    ax.set_ylabel(r'Simulated $(\mathrm{m}^3/\mathrm{s})$', fontsize=16)
    ax.set_title(f'{NameMetric}' + ' = ' + str(round(BestAREM, 2)) + r' $(\mathrm{m}^3/\mathrm{s})$', fontsize=16)

    # Plot Dotty Z-Params
    ax = axes[1]
    ax.scatter(Params[:, 0], Metric, s=30, color=[1, 0.656, 0], alpha=0.2)
    ax.scatter(BestParams[0], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'$Z$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(\mathrm{m}^3/\mathrm{s})$', fontsize=16)
    ax.set_title(r'$Z = ' + str(BestParams[0]) + r'$', fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[2]
    ax.scatter(Params[:, 1], Metric, s=30, color=[0.969, 0, 1], alpha=0.2)
    ax.scatter(BestParams[1], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Factor$_{K_c}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(\mathrm{m}^3/\mathrm{s})$', fontsize=16)
    ax.set_title(r'Factor$_{K_c}$ = ' + str(BestParams[1]), fontsize=16)

    # Save Figure
    FileName = os.path.join(ProjectPath, 'FIGURES', 'Calibration_AWY.jpg')
    plt.tight_layout()
    plt.savefig(FileName)

    try:
        # Conectar con Excel
        excel = win32com.client.Dispatch("Excel.Application")
        workbook = excel.Workbooks.Open(InVEST_Main_Path)

        # Seleccionar la hoja 'Params'
        sheet = workbook.Sheets("Params")

        # Asignar valores a las celdas E2 y E3
        sheet.Range("E2").Value = BestParams[0]
        sheet.Range("E3").Value = BestParams[1]

        # Guardar los cambios (si no quieres guardar, puedes omitir esta línea)
        workbook.Save()

        print("Valores asignados correctamente en el archivo abierto.")

        # Cerrar el libro sin cerrar Excel (opcional)
        workbook.Close(SaveChanges=True)

    except Exception as e:
        print(f"Se produjo un error: {e}")

    finally:
        # Liberar la instancia de Excel (importante para evitar procesos colgados)
        excel.Quit()

def Plot_SWY(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):

    # Metric and parameters
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'SWY_Metric_{Suffix}.csv')
    Tmp         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Params      = Tmp[:, :4]
    Metric      = Tmp[:, 4]

    # Observed
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'SWY_Obs_{Suffix}.csv')
    Obs         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    NGauges     = len(Obs) // len(Metric)
    Obs         = Obs.reshape(len(Metric),NGauges)
    Obs         = Obs.transpose()
    Obs         = Obs[:, 0]
    Obs         = Obs.reshape(NGauges,1)

    # Simulation
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'SWY_Sim_{Suffix}.csv')
    Sim         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Sim         = Sim.reshape(len(Metric),len(Sim) // len(Metric))
    Sim         = Sim.transpose()

    # Best Parameters
    id_min      = np.argmin(Metric)
    BestParams  = Params[id_min, :]
    BestAREM    = FactorMetric * Metric[id_min]
    Metric      = FactorMetric * Metric

    # Scatter Plot
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))

    # Plot Obs Vs Sim
    ax = axes[0,0]
    max_val = max(np.max(Obs), np.max(Sim[:, id_min])) * 1.1
    ax.plot([0, max_val], [0, max_val], linewidth=1.2, color=[0.8, 0.8, 0.8])
    ax.scatter(Obs, Sim[:, id_min], s=100, edgecolor=[0, 0.5, 0.5], facecolor=[0, 0.7, 0.7],alpha=0.2, linewidth=1.2)
    ax.set_xlabel(r'Observed $(mm)$', fontsize=16)
    ax.set_ylabel(r'Simulated $(mm)$', fontsize=16)
    ax.set_title(f'{NameMetric}' + ' = ' + str(round(BestAREM, 2)) + r' $(mm)$', fontsize=16)

    # Plot Dotty Z-Params
    ax = axes[0,1]
    ax.scatter(Params[:, 0], Metric, s=30, color=[1, 0.656, 0], alpha=0.2)
    ax.scatter(BestParams[0], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'\alpha', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(mm)$', fontsize=16)
    ax.set_title(r'\alpha = ' + str(BestParams[0]), fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[0,2]
    ax.scatter(Params[:, 1], Metric, s=30, color=[0.969, 0, 1], alpha=0.2)
    ax.scatter(BestParams[1], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'$\beta$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(mm)$', fontsize=16)
    ax.set_title(r'$\beta$ = ' + str(BestParams[1]), fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[1,0]
    ax.scatter(Params[:, 2], Metric, s=30, color=[0.6, 0.6, 0.6], alpha=0.2)
    ax.scatter(BestParams[2], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'$\gamma$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(mm)$', fontsize=16)
    ax.set_title(r'$\gamma$ = ' + str(BestParams[2]), fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[1,1]
    ax.scatter(Params[:, 3], Metric, s=30, color=[0, 0.5, 0.5], alpha=0.2)
    ax.scatter(BestParams[3], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Factor$_{K_c}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(mm)$', fontsize=16)
    ax.set_title(r'Factor$_{K_c}$ = ' + str(BestParams[3]), fontsize=16)

    # Save Figure
    FileName = os.path.join(ProjectPath, 'FIGURES', 'Calibration_SWY.jpg')
    plt.tight_layout()
    plt.savefig(FileName)

    try:
        # Conectar con Excel
        excel = win32com.client.Dispatch("Excel.Application")
        workbook = excel.Workbooks.Open(InVEST_Main_Path)

        # Seleccionar la hoja 'Params'
        sheet = workbook.Sheets("Params")

        # Asignar valores a las celdas E2 y E3
        sheet.Range("E4").Value = BestParams[0]
        sheet.Range("E5").Value = BestParams[1]
        sheet.Range("E6").Value = BestParams[2]
        sheet.Range("E7").Value = BestParams[3]

        # Guardar los cambios (si no quieres guardar, puedes omitir esta línea)
        workbook.Save()

        print("Valores asignados correctamente en el archivo abierto.")

        # Cerrar el libro sin cerrar Excel (opcional)
        workbook.Close(SaveChanges=True)

    except Exception as e:
        print(f"Se produjo un error: {e}")

    finally:
        # Liberar la instancia de Excel (importante para evitar procesos colgados)
        excel.Quit()

def Plot_SDR(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):

    # Metric and parameters
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'SDR_Metric_{Suffix}.csv')
    Tmp         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Params      = Tmp[:, :6]
    Metric      = Tmp[:, 6]

    # Observed
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'SDR_Obs_{Suffix}.csv')
    Obs         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    NGauges     = len(Obs) // len(Metric)
    Obs         = Obs.reshape(len(Metric),NGauges)
    Obs         = Obs.transpose()
    Obs         = Obs[:, 0]
    Obs         = Obs.reshape(NGauges,1)

    # Simulation
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'SDR_Sim_{Suffix}.csv')
    Sim         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Sim         = Sim.reshape(len(Metric),len(Sim) // len(Metric))
    Sim         = Sim.transpose()

    # Best Parameters
    id_min      = np.argmin(Metric)
    BestParams  = Params[id_min, :]
    BestAREM    = FactorMetric * Metric[id_min]
    Metric      = FactorMetric * Metric

    # Scatter Plot
    fig, axes = plt.subplots(2, 4, figsize=(16, 10))

    # Plot Obs Vs Sim
    ax = axes[0,0]
    max_val = max(np.max(Obs), np.max(Sim[:, id_min])) * 1.1
    ax.plot([0, max_val], [0, max_val], linewidth=1.2, color=[0.8, 0.8, 0.8])
    ax.scatter(Obs, Sim[:, id_min], s=100, edgecolor=[0, 0.5, 0.5], facecolor=[0, 0.7, 0.7],alpha=0.2, linewidth=1.2)
    ax.set_xlabel(r'Observed $(ton/year)$', fontsize=16)
    ax.set_ylabel(r'Simulated $(ton/year)$', fontsize=16)
    ax.set_title(f'{NameMetric}' + ' = ' + str(round(BestAREM, 2)) + r' $(ton/year)$', fontsize=16)

    # Plot Dotty Z-Params
    ax = axes[0,1]
    ax.scatter(Params[:, 0], Metric, s=30, color=[1, 0.656, 0], alpha=0.2)
    ax.scatter(BestParams[0], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'SDR$_{max}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(ton/year)$', fontsize=16)
    ax.set_title(r'SDR$_{max}$ = ' + str(BestParams[0]), fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[0,2]
    ax.scatter(Params[:, 1], Metric, s=30, color=[0.969, 0, 1], alpha=0.2)
    ax.scatter(BestParams[1], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'$K$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(ton/year)$', fontsize=16)
    ax.set_title(r'$K$ = ' + str(BestParams[1]), fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[0,3]
    ax.scatter(Params[:, 2], Metric, s=30, color=[0.6, 0.6, 0.6], alpha=0.2)
    ax.scatter(BestParams[2], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'IC$_{0}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(ton/year)$', fontsize=16)
    ax.set_title(r'IC$_{0}$ = ' + str(BestParams[2]), fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[1,0]
    ax.scatter(Params[:, 3], Metric, s=30, color=[0, 0.5, 0.5], alpha=0.2)
    ax.scatter(BestParams[3], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'L$_{max}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(ton/year)$', fontsize=16)
    ax.set_title(r'L$_{max}$ = ' + str(BestParams[3]), fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[1,1]
    ax.scatter(Params[:, 4], Metric, s=30, color=[0, 0.5, 0.5], alpha=0.2)
    ax.scatter(BestParams[4], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Factor$_{P}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(ton/year)$', fontsize=16)
    ax.set_title(r'Factor$_{P}$ = ' + str(BestParams[4]), fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[1,2]
    ax.scatter(Params[:, 5], Metric, s=30, color=[0, 0.5, 0.5], alpha=0.2)
    ax.scatter(BestParams[5], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Factor$_{C}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(ton/year)$', fontsize=16)
    ax.set_title(r'Factor$_{C}$ = ' + str(BestParams[5]), fontsize=16)

    # Save Figure
    FileName = os.path.join(ProjectPath, 'FIGURES', 'Calibration_SDR.jpg')
    plt.tight_layout()
    plt.savefig(FileName)

    try:
        # Conectar con Excel
        excel = win32com.client.Dispatch("Excel.Application")
        workbook = excel.Workbooks.Open(InVEST_Main_Path)

        # Seleccionar la hoja 'Params'
        sheet = workbook.Sheets("Params")

        # Asignar valores a las celdas E2 y E3
        sheet.Range("E8").Value     = BestParams[0]
        sheet.Range("E9").Value     = BestParams[1]
        sheet.Range("E10").Value    = BestParams[2]
        sheet.Range("E11").Value    = BestParams[3]
        sheet.Range("E12").Value    = BestParams[4]
        sheet.Range("E13").Value    = BestParams[5]

        # Guardar los cambios (si no quieres guardar, puedes omitir esta línea)
        workbook.Save()

        print("Valores asignados correctamente en el archivo abierto.")

        # Cerrar el libro sin cerrar Excel (opcional)
        workbook.Close(SaveChanges=True)

    except Exception as e:
        print(f"Se produjo un error: {e}")

    finally:
        # Liberar la instancia de Excel (importante para evitar procesos colgados)
        excel.Quit()

def Plot_NDR_N(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):

    # Metric and parameters
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'NDR_N_Metric_{Suffix}.csv')
    Tmp         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Params      = Tmp[:, :5]
    Metric      = Tmp[:, 5]

    # Observed
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'NDR_N_Obs_{Suffix}.csv')
    Obs         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    NGauges     = len(Obs) // len(Metric)
    Obs         = Obs.reshape(len(Metric),NGauges)
    Obs         = Obs.transpose()
    Obs         = Obs[:, 0]
    Obs         = Obs.reshape(NGauges,1)

    # Simulation
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'NDR_N_Sim_{Suffix}.csv')
    Sim         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Sim         = Sim.reshape(len(Metric),len(Sim) // len(Metric))
    Sim         = Sim.transpose()

    # Best Parameters
    id_min      = np.argmin(Metric)
    BestParams  = Params[id_min, :]
    BestAREM    = FactorMetric * Metric[id_min]
    Metric      = FactorMetric * Metric

    # Scatter Plot
    fig, axes = plt.subplots(2, 4, figsize=(16, 10))

    # Plot Obs Vs Sim
    ax = axes[0,0]
    max_val = max(np.max(Obs), np.max(Sim[:, id_min])) * 1.1
    ax.plot([0, max_val], [0, max_val], linewidth=1.2, color=[0.8, 0.8, 0.8])
    ax.scatter(Obs, Sim[:, id_min], s=100, edgecolor=[0, 0.5, 0.5], facecolor=[0, 0.7, 0.7],alpha=0.2, linewidth=1.2)
    ax.set_xlabel(r'Observed $(kg/year)$', fontsize=16)
    ax.set_ylabel(r'Simulated $(kg/year)$', fontsize=16)
    ax.set_title(f'{NameMetric}' + ' = ' + str(round(BestAREM, 2)) + r' $(kg/year)$', fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[0,1]
    ax.scatter(Params[:, 0], Metric, s=30, color=[0.6, 0.6, 0.6], alpha=0.2)
    ax.scatter(BestParams[0], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'SubCri$_{Len_N}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'SubCri$_{Len_N}$ = ' + str(BestParams[0]), fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[0,2]
    ax.scatter(Params[:, 1], Metric, s=30, color=[0, 0.5, 0.5], alpha=0.2)
    ax.scatter(BestParams[1], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'SubCri$_{Eff_N}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'SubCri$_{Eff_N}$ = ' + str(BestParams[1]), fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[0,3]
    ax.scatter(Params[:, 2], Metric, s=30, color=[0, 0.5, 0.5], alpha=0.2)
    ax.scatter(BestParams[2], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Borselli$_{K}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'Borselli$_{K}$ = ' + str(BestParams[2]), fontsize=16)

    # Plot Dotty Z-Params
    ax = axes[1,0]
    ax.scatter(Params[:, 3], Metric, s=30, color=[1, 0.656, 0], alpha=0.2)
    ax.scatter(BestParams[3], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Factor$_{Load_N}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'Factor$_{Load_N}$ = ' + str(BestParams[3]), fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[1,1]
    ax.scatter(Params[:, 4], Metric, s=30, color=[0.969, 0, 1], alpha=0.2)
    ax.scatter(BestParams[4], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Factor$_{Eff_N}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'Factor$_{Eff_N}$ = ' + str(BestParams[4]), fontsize=16)

    # Save Figure
    FileName = os.path.join(ProjectPath, 'FIGURES', 'Calibration_NDR_N.jpg')
    plt.tight_layout()
    plt.savefig(FileName)

    try:
        # Conectar con Excel
        excel = win32com.client.Dispatch("Excel.Application")
        workbook = excel.Workbooks.Open(InVEST_Main_Path)

        # Seleccionar la hoja 'Params'
        sheet = workbook.Sheets("Params")

        # Asignar valores a las celdas E2 y E3
        sheet.Range("E14").Value = BestParams[0]
        sheet.Range("E15").Value = BestParams[1]
        sheet.Range("E16").Value = BestParams[2]
        sheet.Range("E17").Value = BestParams[3]
        sheet.Range("E18").Value = BestParams[4]

        # Guardar los cambios (si no quieres guardar, puedes omitir esta línea)
        workbook.Save()

        print("Valores asignados correctamente en el archivo abierto.")

        # Cerrar el libro sin cerrar Excel (opcional)
        workbook.Close(SaveChanges=True)

    except Exception as e:
        print(f"Se produjo un error: {e}")

    finally:
        # Liberar la instancia de Excel (importante para evitar procesos colgados)
        excel.Quit()

def Plot_NDR_P(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):

    # Metric and parameters
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'NDR_P_Metric_{Suffix}.csv')
    Tmp         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Params      = Tmp[:, :3]
    Metric      = Tmp[:, 3]

    # Observed
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'NDR_P_Obs_{Suffix}.csv')
    Obs         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    NGauges     = len(Obs) // len(Metric)
    Obs         = Obs.reshape(len(Metric),NGauges)
    Obs         = Obs.transpose()
    Obs         = Obs[:, 0]
    Obs         = Obs.reshape(NGauges,1)

    # Simulation
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'NDR_P_Sim_{Suffix}.csv')
    Sim         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Sim         = Sim.reshape(len(Metric),len(Sim) // len(Metric))
    Sim         = Sim.transpose()

    # Best Parameters
    id_min      = np.argmin(Metric)
    BestParams  = Params[id_min, :]
    BestAREM    = FactorMetric * Metric[id_min]
    Metric      = FactorMetric * Metric

    # Scatter Plot
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))

    # Plot Obs Vs Sim
    ax = axes[0,0]
    max_val = max(np.max(Obs), np.max(Sim[:, id_min])) * 1.1
    ax.plot([0, max_val], [0, max_val], linewidth=1.2, color=[0.8, 0.8, 0.8])
    ax.scatter(Obs, Sim[:, id_min], s=100, edgecolor=[0, 0.5, 0.5], facecolor=[0, 0.7, 0.7],alpha=0.2, linewidth=1.2)
    ax.set_xlabel(r'Observed $(kg/year)$', fontsize=16)
    ax.set_ylabel(r'Simulated $(kg/year)$', fontsize=16)
    ax.set_title(f'{NameMetric}' + ' = ' + str(round(BestAREM, 2)) + r' $(kg/year)$', fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[0,1]
    ax.scatter(Params[:, 0], Metric, s=30, color=[0, 0.5, 0.5], alpha=0.2)
    ax.scatter(BestParams[0], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Borselli$_{K}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'Borselli$_{K}$ = ' + str(BestParams[0]), fontsize=16)

    # Plot Dotty Z-Params
    ax = axes[0,2]
    ax.scatter(Params[:, 1], Metric, s=30, color=[1, 0.656, 0], alpha=0.2)
    ax.scatter(BestParams[1], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Factor$_{Load_P}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'Factor$_{Load_P}$ = ' + str(BestParams[1]), fontsize=16)

    # Plot Dotty Factor-Kc
    ax = axes[1,0]
    ax.scatter(Params[:, 2], Metric, s=30, color=[0.969, 0, 1], alpha=0.2)
    ax.scatter(BestParams[2], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Factor$_{Eff_P}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'Factor$_{Eff_P}$ = ' + str(BestParams[2]), fontsize=16)

    # Save Figure
    FileName = os.path.join(ProjectPath, 'FIGURES', 'Calibration_NDR_P.jpg')
    plt.tight_layout()
    plt.savefig(FileName)

    try:
        # Conectar con Excel
        excel = win32com.client.Dispatch("Excel.Application")
        workbook = excel.Workbooks.Open(InVEST_Main_Path)

        # Seleccionar la hoja 'Params'
        sheet = workbook.Sheets("Params")

        # Asignar valores a las celdas E2 y E3
        sheet.Range("E16").Value = BestParams[0]
        sheet.Range("E19").Value = BestParams[1]
        sheet.Range("E20").Value = BestParams[2]

        # Guardar los cambios (si no quieres guardar, puedes omitir esta línea)
        workbook.Save()

        print("Valores asignados correctamente en el archivo abierto.")

        # Cerrar el libro sin cerrar Excel (opcional)
        workbook.Close(SaveChanges=True)

    except Exception as e:
        print(f"Se produjo un error: {e}")

    finally:
        # Liberar la instancia de Excel (importante para evitar procesos colgados)
        excel.Quit()

# --------------------------------------------------------------------------
# Name        : ismember.py
# Author      : E.Taskesen
# Contact     : erdogan@gmail.com
# --------------------------------------------------------------------------
# %% ismember
def ismember(a_vec, b_vec, method=None):
    """

    Description
    -----------
    MATLAB equivalent ismember function
    [LIA,LOCB] = ISMEMBER(A,B) also returns an array LOCB containing the
    lowest absolute index in B for each element in A which is a member of
    B and 0 if there is no such index.
    Parameters
    ----------
    a_vec : list or array
    b_vec : list or array
    method : None or 'rows' (default: None).
        rows can be used for row-wise matrice comparison.
    Returns an array containing logical 1 (true) where the data in A is found
    in B. Elsewhere, the array contains logical 0 (false)
    -------
    Tuple

    Example
    -------
    a_vec = np.array([1,2,3,None])
    b_vec = np.array([4,1,2])
    Iloc,idx = ismember(a_vec,b_vec)
    a_vec[Iloc] == b_vec[idx]

    """
    # Set types
    a_vec, b_vec = _settypes(a_vec, b_vec)

    # Compute
    if method is None:
        Iloc, idx = _compute(a_vec, b_vec)
    elif method == 'rows':
        if a_vec.shape[0] != b_vec.shape[0]: raise Exception(
            'Error: Input matrices should have same number of columns.')
        # Compute row-wise over the matrices
        out = list(map(lambda x, y: _compute(x, y), a_vec, b_vec))
        # Unzipping
        Iloc, idx = list(zip(*out))
    else:
        Iloc, idx = None, None

    return (Iloc, idx)


# %% Compute
def _settypes(a_vec, b_vec):
    if 'pandas' in str(type(a_vec)):
        a_vec.values[np.where(a_vec.values == None)] = 'NaN'
        a_vec = np.array(a_vec.values)
    if 'pandas' in str(type(b_vec)):
        b_vec.values[np.where(b_vec.values == None)] = 'NaN'
        b_vec = np.array(b_vec.values)
    if isinstance(a_vec, list):
        a_vec = np.array(a_vec)
        # a_vec[a_vec==None]='NaN'
    if isinstance(b_vec, list):
        b_vec = np.array(b_vec)
        # b_vec[b_vec==None]='NaN'

    return a_vec, b_vec


# %% Compute
def _compute(a_vec, b_vec):
    bool_ind = np.isin(a_vec, b_vec)
    common = a_vec[bool_ind]
    [common_unique, common_inv] = np.unique(common, return_inverse=True)
    [b_unique, b_ind] = np.unique(b_vec, return_index=True)
    common_ind = b_ind[np.isin(b_unique, common_unique, assume_unique=True)]

    return bool_ind, common_ind[common_inv]


"""
Zonal Statistics
Vector-Raster Analysis
Copyright 2013 Matthew Perry
Usage:
  zonal_stats.py VECTOR RASTER
  zonal_stats.py -h | --help
  zonal_stats.py --version
Options:
  -h --help     Show this screen.
  --version     Show version.
"""
def bbox_to_pixel_offsets(gt, bbox):
    originX = gt[0]
    originY = gt[3]
    pixel_width = gt[1]
    pixel_height = gt[5]
    x1 = int((bbox[0] - originX) / pixel_width)
    x2 = int((bbox[1] - originX) / pixel_width) + 1

    y1 = int((bbox[3] - originY) / pixel_height)
    y2 = int((bbox[2] - originY) / pixel_height) + 1

    xsize = x2 - x1
    ysize = y2 - y1
    return (x1, y1, xsize, ysize)


def zonal_stats_1(vector_path, raster_path, nodata_value=None, global_src_extent=False):
    rds = gdal.Open(raster_path, GA_ReadOnly)
    assert(rds)
    rb = rds.GetRasterBand(1)
    rgt = rds.GetGeoTransform()

    if nodata_value:
        nodata_value = float(nodata_value)
        rb.SetNoDataValue(nodata_value)

    vds = ogr.Open(vector_path, GA_ReadOnly)  # TODO maybe open update if we want to write stats
    assert(vds)
    vlyr = vds.GetLayer(0)

    # create an in-memory numpy array of the source raster data
    # covering the whole extent of the vector layer
    if global_src_extent:
        # use global source extent
        # useful only when disk IO or raster scanning inefficiencies are your limiting factor
        # advantage: reads raster data in one pass
        # disadvantage: large vector extents may have big memory requirements
        src_offset = bbox_to_pixel_offsets(rgt, vlyr.GetExtent())
        src_array = rb.ReadAsArray(*src_offset)

        # calculate new geotransform of the layer subset
        new_gt = (
            (rgt[0] + (src_offset[0] * rgt[1])),
            rgt[1],
            0.0,
            (rgt[3] + (src_offset[1] * rgt[5])),
            0.0,
            rgt[5]
        )

    mem_drv = ogr.GetDriverByName('Memory')
    driver = gdal.GetDriverByName('MEM')

    # Loop through vectors
    stats = []
    feat = vlyr.GetNextFeature()
    while feat is not None:

        if not global_src_extent:
            # use local source extent
            # fastest option when you have fast disks and well indexed raster (ie tiled Geotiff)
            # advantage: each feature uses the smallest raster chunk
            # disadvantage: lots of reads on the source raster
            src_offset = bbox_to_pixel_offsets(rgt, feat.geometry().GetEnvelope())
            src_array = rb.ReadAsArray(*src_offset)

            # calculate new geotransform of the feature subset
            new_gt = (
                (rgt[0] + (src_offset[0] * rgt[1])),
                rgt[1],
                0.0,
                (rgt[3] + (src_offset[1] * rgt[5])),
                0.0,
                rgt[5]
            )

        # Create a temporary vector layer in memory
        mem_ds = mem_drv.CreateDataSource('out')
        mem_layer = mem_ds.CreateLayer('poly', None, ogr.wkbPolygon)
        mem_layer.CreateFeature(feat.Clone())

        # Rasterize it
        rvds = driver.Create('', src_offset[2], src_offset[3], 1, gdal.GDT_Byte)
        rvds.SetGeoTransform(new_gt)
        gdal.RasterizeLayer(rvds, [1], mem_layer, burn_values=[1])
        rv_array = rvds.ReadAsArray()

        # Mask the source data array with our current feature
        # we take the logical_not to flip 0<->1 to get the correct mask effect
        # we also mask out nodata values explictly
        masked = np.ma.MaskedArray(
            src_array,
            mask=np.logical_or(
                src_array == nodata_value,
                np.logical_not(rv_array)
            )
        )

        feature_stats = {
            'min': float(masked.min()),
            'mean': float(masked.mean()),
            'max': float(masked.max()),
            'std': float(masked.std()),
            'sum': float(masked.sum()),
            'count': int(masked.count()),
            'fid': int(feat.GetFID())}

        stats.append(feature_stats)

        rvds = None
        mem_ds = None
        feat = vlyr.GetNextFeature()

    vds = None
    rds = None
    return stats

import pyogrio

def calculate_zonal_stats(shapefile_path, raster_path, output_path_shp, ws_id="ws_id", Suffix=""):
    """
    Calcula estadísticas zonales para un raster basado en un shapefile con múltiples polígonos.

    Parámetros:
        shapefile_path (str): Ruta al archivo shapefile.
        raster_path (str): Ruta al archivo raster.
        ws_id (str): Nombre del atributo en el shapefile para agrupar los polígonos.

    Retorna:
        gpd.GeoDataFrame: GeoDataFrame con las estadísticas zonales calculadas.
    """
    try:
        # Cargar el shapefile usando pyogrio como alternativa a Fiona
        polygons = gpd.read_file(shapefile_path, engine='pyogrio')
    except Exception as e:
        raise RuntimeError(f"Error al leer el shapefile: {e}")

    # Verificar que el shapefile y el raster tienen el mismo sistema de referencia
    with rasterio.open(raster_path) as src:
        raster_crs = src.crs
        nodata_value = src.nodatavals[0] if src.nodatavals and src.nodatavals[0] is not None else None

    if polygons.crs != raster_crs:
        polygons = polygons.to_crs(raster_crs)

    # Calcular estadísticas zonales agrupadas por el atributo 'ws_id'
    unique_ids = polygons[ws_id].unique()
    results = []

    for uid in unique_ids:
        subset = polygons[polygons[ws_id] == uid]
        stats = zonal_stats(
            subset,  # Subconjunto del shapefile
            raster_path,  # Archivo raster
            stats=["mean", "min", "max", "median","sum"],
            nodata=nodata_value, # Estadísticas deseadas
            geojson_out=True  # Devuelve los resultados como GeoJSON
        )
        stats_gdf = gpd.GeoDataFrame.from_features(stats)
        stats_gdf[ws_id] = uid
        results.append(stats_gdf)

    # Combinar todos los resultados
    final_result = gpd.GeoDataFrame(pd.concat(results, ignore_index=True))

    # Guardar los resultados en un nuevo shapefile
    output_path = "Zonal_{}.shp".format(Suffix)
    try:
        final_result.to_file(os.path.join(output_path_shp, output_path), driver='ESRI Shapefile')
    except Exception as e:
        raise RuntimeError(f"Error al guardar el shapefile de salida: {e}")

    # Convertir los resultados a un DataFrame
    final_result = pd.DataFrame(final_result)

    return final_result
