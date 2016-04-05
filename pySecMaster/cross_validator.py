import pandas as pd
import time

from utilities.database_queries import delete_sql_table_rows, df_to_sql,\
    query_all_active_tsids, query_all_tsid_prices, query_source_weights,\
    retrieve_data_vendor_id

__author__ = 'Josh Schertz'
__copyright__ = 'Copyright (C) 2016 Josh Schertz'
__description__ = 'An automated system to store and maintain financial data.'
__email__ = 'josh[AT]joshschertz[DOT]com'
__license__ = 'GNU AGPLv3'
__maintainer__ = 'Josh Schertz'
__status__ = 'Development'
__url__ = 'https://joshschertz.com/'
__version__ = '1.3.1'

'''
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as
    published by the Free Software Foundation, either version 3 of the
    License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''


def cross_validate(db_location, table, tsid_list, weights_df, verbose=False):
    """ Compares the prices from multiple sources, storing the price with the
    highest consensus weight.

    :param db_location: String of the database file directory
    :param table: String of the database table that should be worked on
    :param tsid_list: List of strings, with each string being a tsid
    :param weights_df: DataFrame of the source weights
    :param verbose: Boolean of whether to print debugging statements or not
    """

    validator_start = time.time()

    # List of data vendor names to ignore when cross validating the data. Only
    #   matters when the data source might have data that would be considered.
    source_exclude_list = ['pySecMaster_Consensus']

    source_id_exclude_list = []
    for source in source_exclude_list:
        source_id = retrieve_data_vendor_id(db_location=db_location,
                                            name=source)
        source_id_exclude_list.append(source_id)

    # Cycle through each tsid, running the data cross validator on all sources
    #   and fields available.
    for tsid in tsid_list:

        tsid_start = time.time()

        # DataFrame of all stored prices for this ticker and interval
        tsid_prices_df = query_all_tsid_prices(db_location=db_location,
                                               table=table, tsid=tsid)

        unique_dates = tsid_prices_df.index.get_level_values('date').unique()
        unique_sources = tsid_prices_df.index.\
            get_level_values('data_vendor_id').unique()

        # The consensus_price_df contains the prices from weighted consensus
        consensus_price_df = pd.DataFrame(columns=['date', 'open', 'high',
                                                   'low', 'close', 'volume'])
        # Set the date as the index
        consensus_price_df.set_index(['date'], inplace=True)

        # Cycle through each period, comparing each data source's prices
        for date in unique_dates:

            # ToDo: Either add each field's consensus price to a dictionary,
            #   which is entered into the consensus_price_df upon all fields
            #   being processed, or enter each field's consensus price directly
            #   into the consensus_price_df. Right now, this is doing the later.
            # consensus_prices = {}

            try:
                # Create a DF with for the current period, with the source_ids
                #   as the index and the data_columns as the column headers
                period_df = tsid_prices_df.xs(date, level='date')
            except KeyError:
                # Should never happen
                print('Unable to extract the %s period\'s prices from '
                      'the tsid_prices_df for %s' % (date, tsid))
            finally:
                # Transpose the period_df DataFrame so the source_ids are
                #   columns and the price fields are the rows
                period_df = period_df.transpose()
                # print(period_df)

                # Cycle through each price field for this period's values
                for field_index, field_data in period_df.iterrows():
                    # field_index: string of the index name
                    # field_data: Pandas Series (always??) of the field data

                    # Reset the field consensus for every field processed
                    field_consensus = {}

                    # Cycle through each source's values that are in the
                    #   field_data Series.
                    for source_data in field_data.iteritems():
                        # source_data is a tuple, with the first item is being
                        #   the data_vendor_id and the second being the value.

                        # If the source_data's id is in the exclude list, don't
                        #   use its price when calculating the field consensus.
                        if source_data[0] not in source_id_exclude_list:

                            # Retrieve the weighted consensus for this source
                            source_weight = weights_df.loc[
                                weights_df['data_vendor_id'] == source_data[0],
                                'consensus_weight']

                            if field_consensus:
                                # There is already a value for this field
                                if source_data[1] in field_consensus:
                                    # This source's value has a match in the
                                    #   current consensus. Increase the weight
                                    #   for this price.
                                    field_consensus[source_data[1]] += \
                                        source_weight[0]
                                else:
                                    # The data value from the source does not
                                    #   match this field's consensus
                                    field_consensus[source_data[1]] = \
                                        source_weight[0]

                                    if verbose:
                                        print('The %s value for data vendor %i '
                                              'does not match the consensus '
                                              'value on %s.' %
                                              (field_index, source_data[0],
                                               date))
                            else:
                                # Add the first price to the field_consensus
                                #   dictionary, using the price as the key and
                                #   the source's weight as the item.
                                field_consensus[source_data[1]] = \
                                    source_weight[0]

                    # Insert the highest consensus value for this period into
                    #   the consensus_price_df
                    consensus_value = max(field_consensus.keys())
                    consensus_price_df.ix[date, field_index] = consensus_value

        # Add the vendor id of the pySecMaster_Consensus for these values
        validator_id = retrieve_data_vendor_id(db_location=db_location,
                                               name='pySecMaster_Consensus')
        consensus_price_df.insert(0, 'data_vendor_id', validator_id)

        if verbose:
            print('%s data cross validation took %0.2f seconds to complete.' %
                  (tsid, time.time() - tsid_start))

        if validator_id in unique_sources:
            # Data from the cross validation process has already been saved
            #   to the database before, thus it must be removed before adding
            #   the new calculated values.

            delete_query = ("""DELETE FROM %s
                               WHERE tsid='%s'
                               AND data_vendor_id='%s'""" %
                            (table, tsid, validator_id))

            delete_status = delete_sql_table_rows(db_location=db_location,
                                                  query=delete_query,
                                                  table=table, tsid=tsid)
            if delete_status == 'success':
                # Add the validated values to the relevant price table AFTER
                #   ensuring that the duplicates were deleted successfully
                df_to_sql(df=consensus_price_df, db_location=db_location,
                          sql_table=table, exists='append', item=tsid)

        else:
            # Add the validated values to the relevant price table
            df_to_sql(df=consensus_price_df, db_location=db_location,
                      sql_table=table, exists='append', item=tsid)

    if verbose:
        print('%i tsids have had their sources cross validated taking %0.2f '
              'seconds.' % (len(tsid_list), time.time() - validator_start))


if __name__ == '__main__':

    test_database_location = '/home/josh/Programming/Databases/pySecMaster/' \
                             'pySecMaster_d.db'
    test_table = 'daily_prices'

    test_tsids_df = query_all_active_tsids(db_location=test_database_location,
                                           table=test_table)

    # ToDo: Enable the query_source_weights function once the pySecMaster has
    #   been updated with the consensus information
    # test_source_weights_df = \
    #     query_source_weights(db_location=test_database_location)
    test_source_weights_df = pd.DataFrame([
        {'data_vendor_id': 1, 'consensus_weight': 20},
        {'data_vendor_id': 2, 'consensus_weight': 50}])

    test_tsid_list = test_tsids_df['tsid'].values

    cross_validate(db_location=test_database_location, table=test_table,
                   tsid_list=test_tsid_list,
                   weights_df=test_source_weights_df, verbose=True)
