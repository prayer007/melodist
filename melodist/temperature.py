# -*- coding: utf-8 -*-
###############################################################################################################
# This file is part of MELODIST - MEteoroLOgical observation time series DISaggregation Tool                  #
# a program to disaggregate daily values of meteorological variables to hourly values                         #
#                                                                                                             #
# Copyright (C) 2016  Florian Hanzer (1,2), Kristian Förster (1,2), Benjamin Winter (1,2), Thomas Marke (1)   #
#                                                                                                             #
# (1) Institute of Geography, University of Innsbruck, Austria                                                #
# (2) alpS - Centre for Climate Change Adaptation, Innsbruck, Austria                                         #
#                                                                                                             #
# MELODIST is free software: you can redistribute it and/or modify                                            #
# it under the terms of the GNU General Public License as published by                                        #
# the Free Software Foundation, either version 3 of the License, or                                           #
# (at your option) any later version.                                                                         #
#                                                                                                             #
# MELODIST is distributed in the hope that it will be useful,                                                 #
# but WITHOUT ANY WARRANTY; without even the implied warranty of                                              #
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the                                                #
# GNU General Public License for more details.                                                                #
#                                                                                                             #
# You should have received a copy of the GNU General Public License                                           #
# along with this program.  If not, see <http://www.gnu.org/licenses/>.                                       #
#                                                                                                             #
###############################################################################################################

from __future__ import print_function, division, absolute_import
import melodist
import melodist.util
import numpy as np
import pandas as pd

def disaggregate_temperature(data_daily, method='sine', min_max_time='fix', mod_nighttime=False, max_delta=None, sun_times=None):
    """The disaggregation function for temperature

    Parameters
    ----
    data_daily :      daily data
    method :          method to disaggregate
    min_max_time:     "fix" - min/max temperature at fixed times 7h/14h,
                      "sun_loc" - min/max calculated by sunrise/sunnoon + 2h,
                      "sun_loc_shift" - min/max calculated by sunrise/sunnoon + monthly mean shift,
    max_delta:        maximum monthly temperature shift as returned by get_shift_by_data()
    sun_times:        times of sunrise/noon as returned by get_sun_times()
    """

    if method not in (
        'sine',
    ):
        raise ValueError('Invalid option')

    temp_disagg = pd.Series(index=melodist.util.hourly_index(data_daily.index))

    if method == 'sine':
        # for this option assume time of minimum and maximum and fit cosine function through minimum and maximum temperatures
        hours_per_day = 24
        default_shift_hours = 2

        daylength_thres = 3
        # min / max hour during polar night assumption
        min_loc_polar = 6
        max_loc_polar = 18

        locdf = pd.DataFrame(
            index=data_daily.index,
            columns=[
                'min_loc',
                'max_loc',
                'min_val_before',
                'min_val_cur',
                'min_val_next',
                'max_val_before',
                'max_val_cur',
                'max_val_next',
            ]
        )

        if min_max_time == 'fix':
            # take fixed location for minimum and maximum
            locdf.min_loc = 7
            locdf.max_loc = 14
        elif min_max_time == 'sun_loc':
            # take location for minimum and maximum by sunrise / sunnoon + 2h
            locdf.min_loc = sun_times.sunrise.round() # sun rise round to full hour
            locdf.max_loc = sun_times.sunnoon.round() + default_shift_hours # sun noon round to full hour + fix 2h
        elif min_max_time == 'sun_loc_shift':
            # take location for minimum and maximum by sunrise / sunnoon + monthly delta
            locdf.min_loc = sun_times.sunrise.round() # sun rise round to full hour
            locdf.max_loc = (sun_times.sunnoon + max_delta[locdf.index.month].values).round() # sun noon + shift derived from observed hourly data, round to full hour

            pos = locdf.min_loc > locdf.max_loc
            locdf.loc[pos, 'max_loc'] = sun_times.sunnoon[pos].round() + default_shift_hours # standard shift in this case

        locdf.min_loc = locdf.min_loc.astype(int)
        locdf.max_loc = locdf.max_loc.astype(int)

        locdf.min_val_cur = data_daily.tmin
        locdf.max_val_cur = data_daily.tmax
        locdf.min_val_next = data_daily.tmin.shift(-1, 'D')
        locdf.max_val_next = data_daily.tmax.shift(-1, 'D')
        locdf.loc[locdf.index[-1], 'min_val_next'] = locdf.min_val_cur.iloc[-1]
        locdf.loc[locdf.index[-1], 'max_val_next'] = locdf.max_val_cur.iloc[-1]
        locdf.min_val_before = data_daily.tmin.shift(1, 'D')
        locdf.max_val_before = data_daily.tmax.shift(1, 'D')
        locdf.loc[locdf.index[0], 'min_val_before'] = locdf.min_val_cur.iloc[0]
        locdf.loc[locdf.index[0], 'max_val_before'] = locdf.max_val_cur.iloc[0]

        locdf_day = locdf
        locdf = locdf.reindex(temp_disagg.index, method='ffill')

        # whenever we are before the maximum for the current day, use minimum value of current day for cosine function fitting
        # once we have passed the maximum value use the minimum for next day to ensure smooth transitions
        min_val = locdf.min_val_next.copy()
        min_val[min_val.index.hour < locdf.max_loc] = locdf.min_val_cur

        # whenever we are before the minimum for the current day, use maximum value of day before for cosine function fitting
        # once we have passed the minimum value use the maximum for the current day to ensure smooth transitions
        max_val = locdf.max_val_cur.copy()
        max_val[max_val.index.hour < locdf.min_loc] = locdf.max_val_before

        delta_val = max_val - min_val
        v_trans = min_val + delta_val / 2.
        temp_disagg = pd.Series(index=min_val.index)

        if mod_nighttime:
            before_min = locdf.index.hour <= locdf.min_loc
            between_min_max = (locdf.index.hour > locdf.min_loc) & (locdf.index.hour < locdf.max_loc)
            after_max = locdf.index.hour >= locdf.max_loc
            temp_disagg[before_min]      = v_trans + delta_val / 2. * np.cos(np.pi / (hours_per_day - (locdf.max_loc - locdf.min_loc)) * (hours_per_day - locdf.max_loc + locdf.index.hour))
            temp_disagg[between_min_max] = v_trans + delta_val / 2. * np.cos(1.25 * np.pi + 0.75 * np.pi / (locdf.max_loc - locdf.min_loc) * (locdf.index.hour - locdf.min_loc))
            temp_disagg[after_max]       = v_trans + delta_val / 2. * np.cos(np.pi / (hours_per_day - (locdf.max_loc - locdf.min_loc)) * (locdf.index.hour - locdf.max_loc))
        else:
            temp_disagg = v_trans + (delta_val / 2.) * np.cos(2 * np.pi / hours_per_day * (locdf.index.hour - locdf.max_loc))

        polars = sun_times.daylength < daylength_thres
        if polars.sum() > 0:
            # during polar night, no diurnal variation of temperature is applied
            # instead the daily average calculated using tmin and tmax is applied
            polars_index_hourly = melodist.util.hourly_index(polars[polars].index)
            temp_disagg.loc[polars_index_hourly] = np.nan

            avg_before = (locdf_day.min_val_before + locdf_day.max_val_before) / 2.
            avg_cur = (locdf_day.min_val_cur + locdf_day.max_val_cur) / 2.
            getting_warmers = polars &  (avg_before <= avg_cur)
            getting_colders = polars & ~(avg_before <= avg_cur)

            getting_warmers_min_loc = pd.DatetimeIndex([ts.replace(hour=min_loc_polar) for ts in getting_warmers[getting_warmers].index])
            getting_warmers_max_loc = pd.DatetimeIndex([ts.replace(hour=max_loc_polar) for ts in getting_warmers[getting_warmers].index])
            temp_disagg[getting_warmers_min_loc] = locdf_day.min_val_cur[getting_warmers].values
            temp_disagg[getting_warmers_max_loc] = locdf_day.max_val_cur[getting_warmers].values

            getting_colders_min_loc = pd.DatetimeIndex([ts.replace(hour=min_loc_polar) for ts in getting_colders[getting_colders].index])
            getting_colders_max_loc = pd.DatetimeIndex([ts.replace(hour=max_loc_polar) for ts in getting_colders[getting_colders].index])
            temp_disagg[getting_colders_min_loc] = locdf_day.max_val_cur[getting_colders].values
            temp_disagg[getting_colders_max_loc] = locdf_day.min_val_cur[getting_colders].values

            temp_polars = temp_disagg.loc[polars_index_hourly].copy()
            transition_days = polars[polars.diff() == True].astype(int) # 0 where transition from polar to "normal" mode, 1 where transition from normal to polar

            if len(transition_days) > 0:
                polar_to_normal_days = transition_days.index[transition_days == 0]
                normal_to_polar_days = transition_days.index[transition_days == 1] - pd.Timedelta(days=1)
                add_days = polar_to_normal_days.union(normal_to_polar_days)

                temp_polars = temp_polars.append(temp_disagg[melodist.util.hourly_index(add_days)]).sort_index()

                for day in polar_to_normal_days:
                    min_loc = int(locdf.loc[day].min_loc)
                    temp_polars[day.replace(hour=0):day.replace(hour=min_loc) - pd.Timedelta(hours=1)] = np.nan
                    temp_polars[day.replace(hour=min_loc)] = locdf.min_val_cur[day]

                for day in normal_to_polar_days:
                    max_loc = int(locdf.loc[day].max_loc)
                    temp_polars[day.replace(hour=max_loc) + pd.Timedelta(hours=1):day.replace(hour=23)] = np.nan

            temp_interp = temp_polars.interpolate(method='linear', limit=23)
            temp_disagg[temp_interp.index] = temp_interp

    return temp_disagg


def get_shift_by_data(temp_hourly, lon, lat, time_zone):
    '''function to get max temp shift (monthly) by hourly data
    
    Parameters
    ----
    hourly_data_obs : observed hourly data 
    lat :             latitude in DezDeg
    lon :             longitude in DezDeg
    time_zone:        timezone
    '''
    #prepare a daily index 
    days = temp_hourly.resample('D').max()
    max_delta = days * np.nan

    sun_times = melodist.util.get_sun_times(days.index, lon, lat, time_zone)
    
    #get hourly data day by day
    for index_d, row in days.iteritems():        
        index = index_d.date().isoformat()
        temp_h = temp_hourly[index]
        
        if temp_h.empty or temp_h.isnull().any(): # hasnans:
            max_delta[index] = np.nan
        else:
            #get hour of max temp
            max_temp = temp_h.idxmax().hour
            
            #get sun min/max loction (dez. h)
            sun_maxLocation= (sun_times.sunnoon[index_d])
            
            #get delta
            delta_max = max_temp - sun_maxLocation
    
            #write to daily pd df
            max_delta[index] = delta_max
        
    months = max_delta.resample('M').mean()
    data_month_mean = months.groupby(months.index.month).agg('mean')
    shift_max_month_mean = data_month_mean.transpose()
    
    return shift_max_month_mean #max_delta
