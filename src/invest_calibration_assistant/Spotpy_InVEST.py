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

gdal.PushErrorHandler('CPLQuietErrorHandler')

def CreateFolder(dir):
    try:
        os.makedirs(dir)
    except FileExistsError:
        # directory already exists
        pass

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
        Table.loc[Table['Status_Cal_Kc'] == 1, 'Kc'] = Values.loc[Table['Status_Cal_Kc'] == 1]

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
            Table.loc[Table['Status_Cal_Kc'] == 1, 'Kc_' + str(ij)] = Values.loc[Table['Status_Cal_Kc'] == 1]

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
        Table.loc[Table['Status_Cal_C'] == 1, 'usle_c'] = Values.loc[Table['Status_Cal_C'] == 1]

        # Aplica el factor multiplicador a los valores del factor P y redondea a 2 decimales
        Values = round(Table['usle_p'] * round(Params['Factor-P'], 2), 2)
        # Si el factor hace que el P sea mayor que 1, limita el valor a 1
        Values[Values > 1] = 1
        # Asigna los valores de C modificados a la tabla
        Table.loc[Table['Status_Cal_P'] == 1, 'usle_p'] = Values.loc[Table['Status_Cal_P'] == 1]

    # Nutrient Delivery Ratio
    if (UserData['Status_NDR_N'] == 1):
        Values = round(Table['load_n'] * Params['Factor_Load_N'], 3)
        Table.loc[Table['Status_Cal_Load_N'] == 1, 'load_n'] = Values.loc[Table['Status_Cal_Load_N'] == 1]

        Values = round(Table['eff_n'] * Params['Factor_Eff_N'], 2)
        Table.loc[Table['Status_Cal_Eff_N'] == 1, 'eff_n'] = Values.loc[Table['Status_Cal_Eff_N'] == 1]

    if (UserData['Status_NDR_P'] == 1):
        Values = round(Table['load_p'] * Params['Factor_Load_P'], 3)
        Table.loc[Table['Status_Cal_Load_P'] == 1, 'load_p'] = Values.loc[Table['Status_Cal_Load_P'] == 1]

        Values = round(Table['eff_p'] * Params['Factor_Eff_P'], 2)
        Table.loc[Table['Status_Cal_Eff_P'] == 1, 'eff_p'] = Values.loc[Table['Status_Cal_Eff_P'] == 1]

    # Carbons
    # if UserData['Status_CO2'] == 1:
    #    print('')

    return Table

def Cal_FunObj(Obs, Sim, NameFunObj):

    if NameFunObj == "Mean Square Error (MSE)":
        return spotpy.objectivefunctions.mse(Obs, Sim)
    elif NameFunObj == "Mean Absolute Error (MAE)":
        return spotpy.objectivefunctions.mae(Obs, Sim)
    elif NameFunObj == "Root Mean Square Error (RMSE)":
        return spotpy.objectivefunctions.rmse(Obs, Sim)
    elif NameFunObj == "Relative Root Mean Squared Error (RRMSE)":
        return spotpy.objectivefunctions.rrmse(Obs, Sim)

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
    # Metric ya viene con FactorMetric aplicado (FactorMetric*RMSE), por lo que
    # volver a multiplicar por FactorMetric antes de comparar recupera el RMSE
    # real, sin importar si el algoritmo internamente maximiza (DDS) o minimiza
    # (SCE-UA/LHS).
    id_min          = np.argmin(FactorMetric * Metric)
    BestParams      = Params[id_min, :]
    BestParamsDict  = dict(zip(['Z', 'Factor-Kc'], BestParams))
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
    FileName = os.path.join(ProjectPath, 'FIGURES', f'Calibration_AWY_{Suffix}.jpg')
    plt.tight_layout()
    plt.savefig(FileName)
    plt.close()

    return BestParamsDict

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
    # Metric ya viene con FactorMetric aplicado (FactorMetric*RMSE), por lo que
    # volver a multiplicar por FactorMetric antes de comparar recupera el RMSE
    # real, sin importar si el algoritmo internamente maximiza (DDS) o minimiza
    # (SCE-UA/LHS).
    id_min          = np.argmin(FactorMetric * Metric)
    BestParams      = Params[id_min, :]
    BestParamsDict  = dict(zip(['Alpha', 'Beta', 'Gamma', 'Factor-Kc_m'], BestParams))
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
    FileName = os.path.join(ProjectPath, 'FIGURES', f'Calibration_SWY_{Suffix}.jpg')
    plt.tight_layout()
    plt.savefig(FileName)
    plt.close()

    return BestParamsDict

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
    # Metric ya viene con FactorMetric aplicado (FactorMetric*RMSE), por lo que
    # volver a multiplicar por FactorMetric antes de comparar recupera el RMSE
    # real, sin importar si el algoritmo internamente maximiza (DDS) o minimiza
    # (SCE-UA/LHS).
    id_min          = np.argmin(FactorMetric * Metric)
    BestParams      = Params[id_min, :]
    # Orden de columnas tal como se escribe en SDR_Metric_{Suffix}.csv:
    # sdr_max, k_param, ic_0_param, l_max, Factor-C, Factor-P
    BestParamsDict  = dict(zip(
        ['sdr_max', 'Borselli-K_SDR', 'IC0', 'L_max', 'Factor-C', 'Factor-P'],
        BestParams))
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

    # Plot Dotty Factor-C
    ax = axes[1,1]
    ax.scatter(Params[:, 4], Metric, s=30, color=[0, 0.5, 0.5], alpha=0.2)
    ax.scatter(BestParams[4], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Factor$_{C}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(ton/year)$', fontsize=16)
    ax.set_title(r'Factor$_{C}$ = ' + str(BestParams[4]), fontsize=16)

    # Plot Dotty Factor-P
    ax = axes[1,2]
    ax.scatter(Params[:, 5], Metric, s=30, color=[0, 0.5, 0.5], alpha=0.2)
    ax.scatter(BestParams[5], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Factor$_{P}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(ton/year)$', fontsize=16)
    ax.set_title(r'Factor$_{P}$ = ' + str(BestParams[5]), fontsize=16)

    # Save Figure
    FileName = os.path.join(ProjectPath, 'FIGURES', f'Calibration_SDR_{Suffix}.jpg')
    plt.tight_layout()
    plt.savefig(FileName)
    plt.close()

    return BestParamsDict

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
    # Metric ya viene con FactorMetric aplicado (FactorMetric*RMSE), por lo que
    # volver a multiplicar por FactorMetric antes de comparar recupera el RMSE
    # real, sin importar si el algoritmo internamente maximiza (DDS) o minimiza
    # (SCE-UA/LHS).
    id_min          = np.argmin(FactorMetric * Metric)
    BestParams      = Params[id_min, :]
    BestParamsDict  = dict(zip(
        ['SubCri_Len_N', 'Sub_Eff_N', 'Borselli-K_NDR', 'Factor_Load_N', 'Factor_Eff_N'],
        BestParams))
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
    ax.set_xlabel(r'Sub$_{Eff_N}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'Sub$_{Eff_N}$ = ' + str(BestParams[1]), fontsize=16)

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
    FileName = os.path.join(ProjectPath, 'FIGURES', f'Calibration_NDR_N_{Suffix}.jpg')
    plt.tight_layout()
    plt.savefig(FileName)
    plt.close()

    return BestParamsDict

def Plot_NDR_P(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):

    # Metric and parameters
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'NDR_P_Metric_{Suffix}.csv')
    Tmp         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Params      = Tmp[:, :5]
    Metric      = Tmp[:, 5]

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
    # Metric ya viene con FactorMetric aplicado (FactorMetric*RMSE), por lo que
    # volver a multiplicar por FactorMetric antes de comparar recupera el RMSE
    # real, sin importar si el algoritmo internamente maximiza (DDS) o minimiza
    # (SCE-UA/LHS).
    id_min          = np.argmin(FactorMetric * Metric)
    BestParams      = Params[id_min, :]
    BestParamsDict  = dict(zip(
        ['SubCri_Len_P', 'Sub_Eff_P', 'Borselli-K_NDR', 'Factor_Load_P', 'Factor_Eff_P'],
        BestParams))
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

    # Plot Dotty SubCri_Len_P
    ax = axes[0,1]
    ax.scatter(Params[:, 0], Metric, s=30, color=[0.6, 0.6, 0.6], alpha=0.2)
    ax.scatter(BestParams[0], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'SubCri$_{Len_P}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'SubCri$_{Len_P}$ = ' + str(BestParams[0]), fontsize=16)

    # Plot Dotty Sub_Eff_P
    ax = axes[0,2]
    ax.scatter(Params[:, 1], Metric, s=30, color=[0, 0.5, 0.5], alpha=0.2)
    ax.scatter(BestParams[1], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Sub$_{Eff_P}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'Sub$_{Eff_P}$ = ' + str(BestParams[1]), fontsize=16)

    # Plot Dotty Borselli-K
    ax = axes[0,3]
    ax.scatter(Params[:, 2], Metric, s=30, color=[0, 0.5, 0.5], alpha=0.2)
    ax.scatter(BestParams[2], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Borselli$_{K}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'Borselli$_{K}$ = ' + str(BestParams[2]), fontsize=16)

    # Plot Dotty Factor_Load_P
    ax = axes[1,0]
    ax.scatter(Params[:, 3], Metric, s=30, color=[1, 0.656, 0], alpha=0.2)
    ax.scatter(BestParams[3], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Factor$_{Load_P}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'Factor$_{Load_P}$ = ' + str(BestParams[3]), fontsize=16)

    # Plot Dotty Factor_Eff_P
    ax = axes[1,1]
    ax.scatter(Params[:, 4], Metric, s=30, color=[0.969, 0, 1], alpha=0.2)
    ax.scatter(BestParams[4], BestAREM, s=50, color=[1, 0, 0])
    ax.set_xlabel(r'Factor$_{Eff_P}$', fontsize=16)
    ax.set_ylabel(f'{NameMetric}' + r' $(kg/year)$', fontsize=16)
    ax.set_title(r'Factor$_{Eff_P}$ = ' + str(BestParams[4]), fontsize=16)

    # Save Figure
    FileName = os.path.join(ProjectPath, 'FIGURES', f'Calibration_NDR_P_{Suffix}.jpg')
    plt.tight_layout()
    plt.savefig(FileName)
    plt.close()

    return BestParamsDict

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
