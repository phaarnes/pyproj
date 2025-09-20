#!/usr/bin/env python
###############################################################################
# $Id$
#
#  Project:  PROJ
#  Purpose:  Build SRS and coordinate transform database
#  Author:   Even Rouault <even.rouault at spatialys.com>
#
###############################################################################
#  Copyright (c) 2018, Even Rouault <even.rouault at spatialys.com>
#
#  Permission is hereby granted, free of charge, to any person obtaining a
#  copy of this software and associated documentation files (the "Software"),
#  to deal in the Software without restriction, including without limitation
#  the rights to use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of the Software, and to permit persons to whom the
#  Software is furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included
#  in all copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
#  OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
#  THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
###############################################################################


###  MODIFIED VERSION OF THE EQUINOR SCRIPT TO MAKE IT WORK WITH NEW PROJ VERSIONS BY PH 19.09.2025 PER HELGE AARNESEN 19.09.2025

import os
import re
import sqlite3
import sys
import logging

EPSG_AUTHORITY = 'EPSG'
EQNR_AUTHORITY = 'Equinor'
SUMMARY_TEXT = '\n\n***SUMMARY EQUINOR DATA:***\n'
SKIP_BOUND_CRS = True
_INSERT_AUTH_CODE_RE = re.compile(r"INSERT INTO \"[^\"]+\" VALUES\('([^']+)'\s*,\s*'([^']+)'")



def get_authority_from_tablename_and_code(proj_db_cursor, object_table_name, object_code, silent = False):
    data_source = EPSG_AUTHORITY
    key_name = ""
    if(object_table_name == 'epsg_namingsystem'):
        key_name = "naming_system_code"
    elif(object_table_name == 'epsg_coordinatesystem'):
            key_name = "coord_sys_code"
    elif(object_table_name == 'epsg_coordoperation'):
        key_name = "coord_op_code"
    elif(object_table_name == 'epsg_coordinateaxisname'):
        key_name = "coord_axis_name_code"
    elif(object_table_name == 'epsg_unitofmeasure'):
        key_name = "uom_code"
    elif(object_table_name == 'epsg_ellipsoid'):
        key_name = "ellipsoid_code"
    elif(object_table_name == 'epsg_primemeridian'):
        key_name = "prime_meridian_code"
    elif (object_table_name == 'epsg_datum'):
        key_name = "datum_code"
    elif(object_table_name == 'epsg_extent'):
        key_name = "extent_code"
    elif(object_table_name == 'epsg_scope'):
        key_name = "scope_code"
    elif(object_table_name == 'epsg_coordinatereferencesystem'):
        key_name = "coord_ref_sys_code"
    elif (not silent):
        print("Did not recognize input object_table_name in method get_authority_from_tablename_and_code, object_table_name is %s" % object_table_name)

    sql = "SELECT data_source FROM epsg.%s WHERE %s = %i" % (object_table_name, key_name, object_code)
    proj_db_cursor.execute(sql)
    result = proj_db_cursor.fetchone()
    if (result):
        data_source = result[0]
    elif (not silent):
        print("Failed to get authority for", object_table_name, object_code, "from input data, setting data_source default to EPSG")
    return data_source



def _extract_auth_and_code_from_insert(insert_line: str):
    """Extract (authority, code) from an INSERT sql dump line.

    Expected pattern (beginning):
        INSERT INTO "table" VALUES('AUTH','CODE', ...)

    Returns: (authority: str, code: Union[int,str]) or (None, None) if not matched.
    Numeric codes are converted to int (mirroring earlier usage_map population logic).
    """
    m = _INSERT_AUTH_CODE_RE.search(insert_line)
    if not m:
        return None, None
    auth, code = m.group(1), m.group(2)
    # Mirror earlier numeric casting logic
    if code and code[0].isdigit():
        try:
            code_int = int(code)
            code = code_int
        except ValueError:
            # leave as string if not a pure int
            pass
    return auth, code


def addToSummary(text):
    global SUMMARY_TEXT
    SUMMARY_TEXT += "\n" + text

def printSummary():
    print(SUMMARY_TEXT)


def ingest_sqlite_dump(cursor, filename):
    sql = ''
    f = open(filename, 'rb')
    # Skip UTF-8 BOM
    if f.read(3) != b'\xEF\xBB\xBF':
        f.seek(0, os.SEEK_SET)

    count = 0
    for line in f.readlines():
        line = line.replace(b'\r\n', b'\n')
        if sys.version_info >= (3, 0, 0):
            line = line.decode('utf-8') #python3
        else:
            line = str(line) # python2

        # Historically this script was developped with code columns using TEXT
        # so keep it that way to minimized changes in it, and in the diff of
        # generated .sql files
        line = line.replace('INTEGER_OR_TEXT', 'TEXT')

        # Same for WITHOUT ROWID
        line = line.replace('WITHOUT ROWID', '')

        #Filter out GIGS data received from EGR
        matches = ["GIGS"]

        if any(x in line for x in matches):
            count = count + 1
        else:
            sql += line
            if sqlite3.complete_statement(sql):
                sql = sql.strip()
                if sql != 'COMMIT;':
                    try:
                        lower_sql = sql.lower().strip()
                        # Skip INSERTs targeting tables not in PROJ schema or flagged to skip
                        if SKIP_BOUND_CRS and ('insert into gs_boundcoordrefsystem' in lower_sql or 'insert into "gs_boundcoordrefsystem"' in lower_sql):
                            logging.info('Skipping bound CRS row from %s', filename)
                        else:
                            cursor.execute(sql)

                    except:
                        print(sql)
                        raise
                sql = ''

    addToSummary("NUMBER OF GIGS LINES from EGR that is skipped %i" % count)

def ingest_epsg():

    for f in ['PostgreSQL_Data_Script.sql',  'PostgreSQL_Table_Script.sql']:
        if not os.path.exists(f):
            raise Exception('Missing file: ' + f)

    epsg_tmp_db_filename = 'tmp_epsg.db'

    if os.path.exists(epsg_tmp_db_filename):
        os.unlink(epsg_tmp_db_filename)

    conn = sqlite3.connect(epsg_tmp_db_filename)
    cursor = conn.cursor()
    cursor.execute('PRAGMA journal_mode = OFF;')
    ingest_sqlite_dump(cursor, 'PostgreSQL_Table_Script.sql')
    ingest_sqlite_dump(cursor, 'PostgreSQL_Data_Script.sql')
    cursor.close()
    conn.commit()

    return (conn, epsg_tmp_db_filename)


def fill_unit_of_measure(proj_db_cursor):
    proj_db_cursor.execute(
        "INSERT INTO unit_of_measure SELECT ?, uom_code, unit_of_meas_name, unit_of_meas_type, factor_b / factor_c, NULL, deprecated FROM epsg.epsg_unitofmeasure", (EPSG_AUTHORITY,))


def fill_ellipsoid(proj_db_cursor):
    proj_db_cursor.execute(
        "INSERT INTO ellipsoid SELECT ?, ellipsoid_code, ellipsoid_name, NULL, 'PROJ', 'EARTH', semi_major_axis, ?, uom_code, inv_flattening, semi_minor_axis, deprecated FROM epsg.epsg_ellipsoid", (EPSG_AUTHORITY, EPSG_AUTHORITY))


def fill_extent(proj_db_cursor):
    #proj_db_cursor.execute(
    #    "INSERT INTO extent SELECT ?, extent_code, extent_name, extent_description, bbox_south_bound_lat, bbox_north_bound_lat, bbox_west_bound_lon, bbox_east_bound_lon, deprecatedFROM epsg.epsg_extent", (EPSG_AUTHORITY,))
    eq_custom_records_count = 0
    proj_db_cursor.execute(
        "SELECT data_source, extent_code, extent_name, extent_description, bbox_south_bound_lat, bbox_north_bound_lat, bbox_west_bound_lon, bbox_east_bound_lon, deprecated FROM epsg.epsg_extent")
    res = proj_db_cursor.fetchall()
    for (data_source, extent_code, extent_name, extent_description, bbox_south_bound_lat, bbox_north_bound_lat, bbox_west_bound_lon, bbox_east_bound_lon, deprecated) in res:
        try:
            # Some new records have longitudes outside [-180,180]
            if bbox_west_bound_lon and bbox_west_bound_lon < -180:
                # print( extent_code, extent_name, extent_description, bbox_south_bound_lat, bbox_north_bound_lat, bbox_west_bound_lon, bbox_east_bound_lon, deprecated)
                bbox_west_bound_lon += 360
            if bbox_east_bound_lon and bbox_east_bound_lon > 180:
                # print( extent_code, extent_name, extent_description, bbox_south_bound_lat, bbox_north_bound_lat, bbox_west_bound_lon, bbox_east_bound_lon, deprecated)
                bbox_east_bound_lon -= 360
            proj_db_cursor.execute(
                "INSERT INTO extent VALUES (?,?,?,?,?,?,?,?,?)", (data_source, extent_code, extent_name, extent_description, bbox_south_bound_lat, bbox_north_bound_lat, bbox_west_bound_lon, bbox_east_bound_lon, deprecated))
            if (EQNR_AUTHORITY == data_source):
                eq_custom_records_count = eq_custom_records_count + 1
        except sqlite3.IntegrityError as e:
            print(e)
            print(extent_code, extent_name, extent_description, bbox_south_bound_lat, bbox_north_bound_lat, bbox_west_bound_lon, bbox_east_bound_lon, deprecated)
            raise
    addToSummary("Added %s EQUINOR extents" % eq_custom_records_count)


def fill_scope(proj_db_cursor):
    eq_custom_records_count = 0
    eq_scope_codes = ""
    proj_db_cursor.execute("SELECT data_source, scope_code, scope, deprecated FROM epsg.epsg_scope")
    res = proj_db_cursor.fetchall()
    for (data_source, scope_code, scope, deprecated) in res:
        proj_db_cursor.execute("INSERT INTO scope VALUES (?,?,?,?)", (data_source, scope_code, scope,deprecated))
        if (EQNR_AUTHORITY == data_source):
            eq_custom_records_count = eq_custom_records_count + 1
            eq_scope_codes += str(scope_code) + ", "
    addToSummary("Added %s EQUINOR scopes, scopes codes are: %s" % (eq_custom_records_count, eq_scope_codes))


def fill_usage(proj_db_cursor):
    eq_custom_crs_usage_count = 0
    eq_custom_co_usage_count = 0
    eq_custom_datum_usage_count = 0
    proj_db_cursor.execute(
        "SELECT usage_code, object_table_name, object_code, extent_code, scope_code FROM epsg.epsg_usage")
    res = proj_db_cursor.fetchall()
    for (usage_code, object_table_name, object_code, extent_code, scope_code) in res:
        print(object_code)

        if object_table_name == "gs_boundcoordrefsystem": # skip bound crs usage
            continue

        authority = get_authority_from_tablename_and_code(proj_db_cursor, object_table_name, object_code)
        if object_table_name == 'epsg_coordinatereferencesystem':
            proj_db_cursor.execute('SELECT table_name FROM crs_view WHERE auth_name = ? AND code = ?', (authority, object_code))
            proj_table_name = proj_db_cursor.fetchone()
            if proj_table_name is None:
                continue
            if (EQNR_AUTHORITY == authority):
                eq_custom_crs_usage_count = eq_custom_crs_usage_count + 1
        elif object_table_name == 'epsg_coordoperation':
            proj_db_cursor.execute("SELECT table_name FROM coordinate_operation_view WHERE auth_name = ? AND code = ? UNION ALL SELECT 'conversion' FROM conversion WHERE auth_name = ? AND code = ?", (authority, object_code, authority, object_code))
            proj_table_name = proj_db_cursor.fetchone()
            if proj_table_name is None:
                continue
            if (EQNR_AUTHORITY == authority):
                eq_custom_co_usage_count = eq_custom_co_usage_count + 1
        elif object_table_name == 'epsg_datum':
            proj_db_cursor.execute("SELECT 'geodetic_datum' FROM geodetic_datum WHERE auth_name = ? AND code = ? UNION ALL SELECT 'vertical_datum' FROM vertical_datum WHERE auth_name = ? AND code = ?", (authority, object_code, authority, object_code))
            proj_table_name = proj_db_cursor.fetchone()
            if proj_table_name is None:
                continue
            if (EQNR_AUTHORITY == authority):
                eq_custom_datum_usage_count = eq_custom_datum_usage_count + 1
        proj_table_name = proj_table_name[0]
        extent_data_source = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_extent", extent_code)
        scope_data_source = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_scope", scope_code)
        proj_db_cursor.execute(
            "INSERT INTO usage VALUES (?,?,?,?,?,?,?,?,?)", (authority, usage_code, proj_table_name, authority, object_code, extent_data_source, extent_code, scope_data_source, scope_code))

    addToSummary("Usage: Added %s equinor usage for CRS" % eq_custom_crs_usage_count)
    addToSummary("Usage: Added %s equinor usage for coordinateoperation" % eq_custom_co_usage_count)
    addToSummary("Usage: Added %s equinor usage for datum" % eq_custom_datum_usage_count)



def fill_prime_meridian(proj_db_cursor):
    proj_db_cursor.execute(
        "INSERT INTO prime_meridian SELECT ?, prime_meridian_code, prime_meridian_name, greenwich_longitude, ?, uom_code, deprecated FROM epsg.epsg_primemeridian", (EPSG_AUTHORITY, EPSG_AUTHORITY))


def compute_publication_date(datum_code, datum_name, frame_reference_epoch, publication_date):
    if frame_reference_epoch is not None:
        epoch = float(frame_reference_epoch)
        fractional = epoch - int(epoch)
        if fractional == 0:
            publication_date = '%04d-01-01' % int(epoch)
        elif abs(fractional - 0.4) < 1e-6:
            publication_date = '%04d-05-01' % int(epoch)
        elif abs(fractional - 0.5) < 1e-6:
            publication_date = '%04d-07-01' % int(epoch)
        else:
            assert False, (datum_code, datum_name, frame_reference_epoch, fractional)
    elif publication_date != '':
        if len(publication_date) == 4:
            publication_date += '-01-01'
        elif len(publication_date) == 7:
            publication_date += '-01'
        elif len(publication_date) == 4+1+4:
            m = re.search('([0-9]{4})-([0-9]{4})', publication_date)
            if m:
                publication_date = m.group(1)
            else:
                assert False, (datum_code, datum_name, publication_date)
        else:
            assert len(publication_date) == 10, (datum_code, datum_name, publication_date)
    else:
        publication_date = None
    return publication_date


def fill_geodetic_datum(proj_db_cursor):
    eq_custom_datum_count = 0
    proj_db_cursor.execute(
        "SELECT DISTINCT * FROM epsg.epsg_datum WHERE datum_type NOT IN ('geodetic', 'dynamic geodetic', 'ensemble', 'vertical', 'engineering')")
    res = proj_db_cursor.fetchall()
    if res:
        raise Exception('Found unexpected datum_type in epsg_datum: %s' % str(res))

    proj_db_cursor.execute("SELECT datum_code, datum_name, ellipsoid_code, prime_meridian_code, data_source, publication_date, frame_reference_epoch, anchor_epoch, deprecated FROM epsg.epsg_datum WHERE datum_type IN ('geodetic', 'dynamic geodetic')")
    res = proj_db_cursor.fetchall()

    for (datum_code, datum_name, ellipsoid_code, prime_meridian_code, data_source, publication_date, frame_reference_epoch, anchor_epoch, deprecated) in res:
        publication_date = compute_publication_date(datum_code, datum_name, frame_reference_epoch, publication_date)
        ellipsoid_datasource = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_ellipsoid", ellipsoid_code, silent = False)
        prime_meridian_datasource = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_primemeridian", prime_meridian_code, silent = False)
        proj_db_cursor.execute(
        "INSERT INTO geodetic_datum VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)", (data_source, datum_code, datum_name, ellipsoid_datasource, ellipsoid_code, prime_meridian_datasource, prime_meridian_code, publication_date, frame_reference_epoch, anchor_epoch, deprecated))

        if (EQNR_AUTHORITY == data_source):
            eq_custom_datum_count = eq_custom_datum_count + 1
    addToSummary("Added %s custom Equinor geodetic datums" % eq_custom_datum_count)


def fill_vertical_datum(proj_db_cursor):
    eq_custom_datum_count = 0
    proj_db_cursor.execute("SELECT datum_code, datum_name, data_source, publication_date, frame_reference_epoch, anchor_epoch, deprecated FROM epsg.epsg_datum WHERE datum_type IN ('vertical')")
    res = proj_db_cursor.fetchall()
    for (datum_code, datum_name, data_source, publication_date, frame_reference_epoch, anchor_epoch, deprecated) in res:
        publication_date = compute_publication_date(datum_code, datum_name, frame_reference_epoch, publication_date)
        proj_db_cursor.execute(
        "INSERT INTO vertical_datum VALUES (?, ?, ?, NULL, ?, ?, NULL, NULL, ?, ?)", (data_source, datum_code, datum_name, publication_date, frame_reference_epoch, anchor_epoch, deprecated))
        if (EQNR_AUTHORITY == data_source):
            eq_custom_datum_count = eq_custom_datum_count + 1
    addToSummary("Added %s custom Equinor vertical datums" % eq_custom_datum_count)


def fill_engineering_datum(proj_db_cursor):
    proj_db_cursor.execute("SELECT datum_code, datum_name, data_source, publication_date, frame_reference_epoch, anchor_epoch, deprecated FROM epsg.epsg_datum WHERE datum_type IN ('engineering') AND datum_name NOT LIKE 'EPSG example%'")
    res = proj_db_cursor.fetchall()
    for (datum_code, datum_name, data_source, publication_date, frame_reference_epoch, anchor_epoch, deprecated) in res:
        publication_date = compute_publication_date(datum_code, datum_name, frame_reference_epoch, publication_date)
        proj_db_cursor.execute(
        "INSERT INTO engineering_datum VALUES (?, ?, ?, ?, NULL, ?, ?)", (data_source, datum_code, datum_name, publication_date, anchor_epoch, deprecated))



def fill_datumensemble(proj_db_cursor):

    proj_db_cursor.execute("SELECT datum_code, datum_name, data_source, ensemble_accuracy, deprecated FROM epsg.epsg_datum JOIN epsg.epsg_datumensemble ON datum_code = datum_ensemble_code WHERE datum_type = 'ensemble'")
    rows = proj_db_cursor.fetchall()
    for (datum_code, datum_name, data_source, ensemble_accuracy, deprecated) in rows:
        assert ensemble_accuracy is not None
        proj_db_cursor.execute("SELECT DISTINCT datum_type, ellipsoid_code, prime_meridian_code FROM epsg.epsg_datum WHERE datum_code IN (SELECT datum_code FROM epsg.epsg_datumensemblemember WHERE datum_ensemble_code = ?)", (datum_code,))
        subrows = proj_db_cursor.fetchall()
        assert len(subrows) == 1, datum_code
        datum_type = subrows[0][0]
        if datum_type == 'vertical':
            datum_ensemble_member_table = 'vertical_datum_ensemble_member'
            proj_db_cursor.execute("INSERT INTO vertical_datum (auth_name, code, name, description, publication_date, frame_reference_epoch, ensemble_accuracy, deprecated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (data_source.strip(), datum_code, datum_name, None, None, None, ensemble_accuracy, deprecated))
            # proj_db_cursor.execute("INSERT INTO vertical_datum (auth_name, code, name, description, publication_date, frame_reference_epoch, ensemble_accuracy, deprecated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (EPSG_AUTHORITY, datum_code, datum_name, None, None, None, ensemble_accuracy, deprecated))
        else:
            datum_ensemble_member_table = 'geodetic_datum_ensemble_member'
            assert datum_type in ('dynamic geodetic', 'geodetic'), datum_code
            ellipsoid_code = subrows[0][1]
            prime_meridian_code = subrows[0][2]
            assert ellipsoid_code, datum_code
            assert prime_meridian_code, datum_code
            ellipsoid_datasource = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_ellipsoid", ellipsoid_code, silent = False)
            prime_meridian_datasource = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_primemeridian", prime_meridian_code, silent = False)
            proj_db_cursor.execute(
            "INSERT INTO geodetic_datum (auth_name, code, name, description, ellipsoid_auth_name, ellipsoid_code, prime_meridian_auth_name, prime_meridian_code, publication_date, frame_reference_epoch, ensemble_accuracy,anchor, deprecated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (data_source, datum_code, datum_name, None, ellipsoid_datasource, ellipsoid_code, prime_meridian_datasource, prime_meridian_code, None, None, ensemble_accuracy, None, deprecated))

        proj_db_cursor.execute("SELECT datum_code, datum_sequence FROM epsg.epsg_datumensemblemember WHERE datum_ensemble_code = ? ORDER by datum_sequence", (datum_code,))
        for member_code, sequence in proj_db_cursor.fetchall():
            proj_db_cursor.execute(
            "INSERT INTO " + datum_ensemble_member_table + " (ensemble_auth_name, ensemble_code, member_auth_name, member_code, sequence) VALUES (?, ?, ?, ?, ?)", (data_source.strip(), datum_code, data_source.strip(), member_code, sequence))
            # proj_db_cursor.execute(
            # "INSERT INTO " + datum_ensemble_member_table + " (ensemble_auth_name, ensemble_code, member_auth_name, member_code, sequence) VALUES (?, ?, ?, ?, ?)", (EPSG_AUTHORITY, datum_code, EPSG_AUTHORITY, member_code, sequence))

handled_coord_sys_type = "('Cartesian', 'vertical', 'ellipsoidal', 'spherical', 'ordinal')"


def find_crs_code_name_extent_from_geodetic_datum_code(proj_db_cursor, datum_code):
    proj_db_cursor.execute("SELECT coord_ref_sys_code, coord_ref_sys_name FROM epsg.epsg_coordinatereferencesystem WHERE coord_ref_sys_kind = 'geographic 2D' AND deprecated = 0 AND datum_code = ?", (datum_code,))
    subrows = proj_db_cursor.fetchall()
    assert len(subrows) == 1, (subrows, datum_code)
    crs_code = subrows[0][0]
    crs_name = subrows[0][1]
    proj_db_cursor.execute("SELECT extent_code FROM epsg.epsg_usage WHERE object_table_name = 'epsg_coordinatereferencesystem' AND object_code = ?", (crs_code,))
    subrows = proj_db_cursor.fetchall()
    assert len(subrows) == 1, (subrows, datum_code)
    # if len(subrows) > 1:
    #     # Pick the first one
    #     logging.warning('Multiple extents for CRS %s, picking the first one', crs_code)

    crs_extent = subrows[0][0]
    return crs_code, crs_name, crs_extent


def find_crs_code_name_extent_from_vertical_datum_code(proj_db_cursor, datum_code):
    proj_db_cursor.execute("SELECT coord_ref_sys_code, coord_ref_sys_name FROM epsg.epsg_coordinatereferencesystem WHERE coord_ref_sys_kind = 'vertical' AND deprecated = 0 AND datum_code = ?", (datum_code,))
    subrows = proj_db_cursor.fetchall()
    assert len(subrows) == 1, (subrows, datum_code)
    crs_code = subrows[0][0]
    crs_name = subrows[0][1]
    proj_db_cursor.execute("SELECT extent_code FROM epsg.epsg_usage WHERE object_table_name = 'epsg_coordinatereferencesystem' AND object_code = ?", (crs_code,))
    subrows = proj_db_cursor.fetchall()
    assert len(subrows) == 1, (subrows, datum_code)
    crs_extent = subrows[0][0]
    return crs_code, crs_name, crs_extent


def create_datumensemble_transformations(proj_db_cursor):

    proj_db_cursor.execute("SELECT data_source, datum_code, datum_name, ensemble_accuracy, deprecated FROM epsg.epsg_datum JOIN epsg.epsg_datumensemble ON datum_code = datum_ensemble_code WHERE datum_type = 'ensemble'")
    rows = proj_db_cursor.fetchall()
    for (data_source, datum_code, datum_name, ensemble_accuracy, deprecated) in rows:
        assert ensemble_accuracy is not None
        proj_db_cursor.execute("SELECT DISTINCT datum_type, ellipsoid_code, prime_meridian_code FROM epsg.epsg_datum WHERE datum_code IN (SELECT datum_code FROM epsg.epsg_datumensemblemember WHERE datum_ensemble_code = ?)", (datum_code,))
        subrows = proj_db_cursor.fetchall()
        assert len(subrows) == 1, datum_code
        datum_type = subrows[0][0]
        if datum_type == 'vertical':
            datum_ensemble_member_table = 'vertical_datum_ensemble_member'
            ensemble_crs_code, ensemble_crs_name, ensemble_crs_extent = find_crs_code_name_extent_from_vertical_datum_code(proj_db_cursor, datum_code)
        else:
            datum_ensemble_member_table = 'geodetic_datum_ensemble_member'
            assert datum_type in ('dynamic geodetic', 'geodetic'), datum_code
            ensemble_crs_code, ensemble_crs_name, ensemble_crs_extent = find_crs_code_name_extent_from_geodetic_datum_code(proj_db_cursor, datum_code)

        proj_db_cursor.execute("SELECT datum_code, datum_sequence FROM epsg.epsg_datumensemblemember WHERE datum_ensemble_code = ? ORDER by datum_sequence", (datum_code,))
        for member_code, sequence in proj_db_cursor.fetchall():

            if datum_ensemble_member_table == 'geodetic_datum_ensemble_member':
                # Insert a null transformation between the representative CRS of the datum ensemble
                # and each representative CRS of its members.
                crs_code, crs_name, crs_extent = find_crs_code_name_extent_from_geodetic_datum_code(proj_db_cursor, member_code)
                assert crs_extent == ensemble_crs_extent or (crs_extent in (2830, 1262) and ensemble_crs_extent in (2830, 1262)) or (ensemble_crs_code == 4258 and ensemble_crs_extent == 4755 and crs_extent == 1298), (ensemble_crs_code, ensemble_crs_name, ensemble_crs_extent, crs_code, crs_name, crs_extent)

                code = '%s_TO_%s' % (ensemble_crs_name, crs_name)
                code = code.replace(' ', '')
                code = code.replace('(', '_')
                code = code.replace(')', '')
                code = code.upper()
                name = '%s to %s' % (ensemble_crs_name, crs_name)
                remarks = 'Accuracy %s m, from datum ensemble definition' % ensemble_accuracy
                method_code = '9603'
                method_name = 'Geocentric translations (geog2D domain)'
                source_crs_code = ensemble_crs_code
                target_crs_code = crs_code
                source_crs_authority = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_datum", source_crs_code)
                target_crs_authority = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_datum", target_crs_code)
                coord_op_accuracy = ensemble_accuracy
                arg = ('PROJ', code, name,
                       remarks,
                       EPSG_AUTHORITY, method_code, method_name,
                       source_crs_authority, source_crs_code,
                       target_crs_authority, target_crs_code,
                       coord_op_accuracy,
                       0,0,0,EPSG_AUTHORITY,'9001',
                       None,None,None,None,None,
                       None,None,None,
                       None,None,None,None,None,
                       None,None,None,None,None,
                       None,None,None,
                       None,None,None,
                       None,None,None,None,None,
                       '',0)

                proj_db_cursor.execute('INSERT INTO helmert_transformation VALUES (' +
                    '?,?,?, ?, ?,?,?, ?,?, ?,?, ?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?,?,?, ?,?)', arg)


                extent_auth_name = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_datum", crs_extent)
                proj_db_cursor.execute('INSERT INTO usage VALUES (?,?,?,?,?,?,?,?,?)',
                                       ('PROJ',
                                        code + '_USAGE',
                                        'helmert_transformation',
                                        'PROJ',
                                        code,
                                        extent_auth_name, crs_extent,
                                        EPSG_AUTHORITY,'1024')) # unknown scope
            else:
                # Insert a null transformation between the representative CRS of the datum ensemble
                # and each representative CRS of its members.
                crs_code, crs_name, crs_extent = find_crs_code_name_extent_from_vertical_datum_code(proj_db_cursor, member_code)

                code = '%s_TO_%s' % (ensemble_crs_name, crs_name)
                code = code.replace(' ', '_')
                code = code.replace('St.', 'St')
                code = code.replace('(', '_')
                code = code.replace(')', '')
                code = code.replace('__', '_')
                code = code.upper()
                name = '%s to %s' % (ensemble_crs_name, crs_name)
                remarks = 'Accuracy %s m, from datum ensemble definition' % ensemble_accuracy
                method_code = '9616'
                method_name = 'Vertical Offset'
                source_crs_code = ensemble_crs_code
                target_crs_code = crs_code
                coord_op_accuracy = ensemble_accuracy
                source_crs_authority = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_datum", source_crs_code)
                target_crs_authority = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_datum", target_crs_code)

                arg = ('PROJ', code, name,
                       remarks,
                       EPSG_AUTHORITY, method_code, method_name,
                       source_crs_authority, source_crs_code,
                       target_crs_authority, target_crs_code,
                       coord_op_accuracy,
                       'EPSG','8603','Vertical Offset',0,'EPSG','9001',
                       None,None,None,None,None,None,
                       None,None,None,None,None,None,
                       None,None,None,None,None,None,
                       None,None,None,None,None,None,
                       None,None,None,None,None,None,
                       None,None,None,None,None,None,
                       None,None,None,None,None,None,
                       None,None,None,None,None,None,
                       None,None,None,None,
                       None,None,
                       '',0)

                proj_db_cursor.execute('INSERT INTO other_transformation VALUES (' +
                    '?,?,?, ?, ?,?,?, ?,?, ?,?,  ?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ' +
                    '?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?, ?,?, ?,?)', arg)

                extent_auth_name = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_datum", crs_extent)
                proj_db_cursor.execute('INSERT INTO usage VALUES (?,?,?,?,?,?,?,?,?)',
                                       ('PROJ',
                                        code + '_USAGE',
                                        'other_transformation',
                                        'PROJ',
                                        code,
                                        extent_auth_name, crs_extent,
                                        EPSG_AUTHORITY,'1024')) # unknown scope

handled_coord_sys_type = "('Cartesian', 'vertical', 'ellipsoidal', 'spherical', 'ordinal')"

def fill_coordinate_system(proj_db_cursor):
    proj_db_cursor.execute(
        "INSERT INTO coordinate_system SELECT data_source, coord_sys_code, coord_sys_type, dimension FROM epsg.epsg_coordinatesystem WHERE coord_sys_type IN " + handled_coord_sys_type)
    proj_db_cursor.execute("SELECT coord_sys_name, coord_sys_code, coord_sys_type, dimension FROM epsg.epsg_coordinatesystem WHERE coord_sys_type NOT IN " + handled_coord_sys_type)
    res = proj_db_cursor.fetchall()
    for (coord_sys_name, coord_sys_code, coord_sys_type, dimension) in res:
        print('Skipping coordinate system %s: %s, it has type %s which is not handled by PROJ' % (coord_sys_code, coord_sys_name, coord_sys_type))


def fill_axis(proj_db_cursor):
    proj_db_cursor.execute(
        "SELECT coord_axis_code,\
                ca.coord_axis_name_code,\
                coord_axis_name,\
                coord_axis_abbreviation,\
                coord_axis_orientation,\
                ca.coord_sys_code,\
                coord_axis_order,\
                uom_code\
        FROM epsg.epsg_coordinateaxis ca \
        LEFT JOIN epsg.epsg_coordinateaxisname can \
        ON ca.coord_axis_name_code = can.coord_axis_name_code \
        JOIN epsg.epsg_coordinatesystem cs \
        ON cs.coord_sys_code = ca.coord_sys_code \
        WHERE coord_sys_type IN " + handled_coord_sys_type)

    res = proj_db_cursor.fetchall();
    for (coord_axis_code,
         coord_axis_name_code,
         coord_axis_name,
         coord_axis_abbreviation,
         coord_axis_orientation,
         coord_sys_code,
         coord_axis_order,
         uom_code) in res:

        coordinateaxisname_auth_name = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinateaxisname", coord_axis_name_code)
        coordinate_system_auth_name = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinatesystem", coord_sys_code)
        uom_auth_name = coordinate_system_auth_name
        if (uom_code):
            uom_auth_name = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_unitofmeasure", uom_code)

        proj_db_cursor.execute("INSERT INTO axis VALUES (?,?,?,?,?,?,?,?,?,?)",\
            (coordinateaxisname_auth_name,
            coord_axis_code,
            coord_axis_name,
            coord_axis_abbreviation,
            coord_axis_orientation,
            coordinate_system_auth_name,
            coord_sys_code,
            coord_axis_order,
            uom_auth_name,
            uom_code))


def fill_geodetic_crs(proj_db_cursor):
    # TODO?: address 'derived'
    proj_db_cursor.execute(
        "SELECT DISTINCT * FROM epsg.epsg_coordinatereferencesystem WHERE coord_ref_sys_kind NOT IN ('projected', 'geographic 2D', 'geographic 3D', 'geocentric', 'vertical', 'compound', 'engineering', 'derived')")
    res = proj_db_cursor.fetchall()
    if res:
        raise Exception('Found unexpected coord_ref_sys_kind in epsg_coordinatereferencesystem: %s' % str(res))

    proj_db_cursor.execute("SELECT data_source, coord_ref_sys_code, coord_ref_sys_name, coord_ref_sys_kind, coord_sys_code, datum_code, deprecated FROM epsg.epsg_coordinatereferencesystem WHERE coord_ref_sys_kind IN ('geographic 2D', 'geographic 3D', 'geocentric') AND datum_code IS NOT NULL")
    res = proj_db_cursor.fetchall()
    for (data_source, coord_ref_sys_code, coord_ref_sys_name, coord_ref_sys_kind, coord_sys_code, datum_code, deprecated) in res:
        datum_authority = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_datum", datum_code)
        coordinate_system_authority = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinatereferencesystem", coord_sys_code)
        print("Inserting geodetic crs auth %s code %s datumAuth: %s datumcode %s" % (data_source, coord_ref_sys_code, datum_authority, datum_code))
        proj_db_cursor.execute("INSERT INTO geodetic_crs VALUES (?,?,?,NULL,?,?,?,?,?,NULL,?)", (data_source, coord_ref_sys_code, coord_ref_sys_name, coord_ref_sys_kind, coordinate_system_authority, coord_sys_code, datum_authority, datum_code, deprecated))
        #try:
        #    proj_db_cursor.execute("INSERT INTO geodetic_crs VALUES (?,?,?,NULL,?,?,?,?,?,NULL,?)", (data_source, coord_ref_sys_code, coord_ref_sys_name, coord_ref_sys_kind, coordinate_system_authority, coord_sys_code, datum_authority, datum_code, deprecated))
        #except:
        #    print("Failed to insert into geodetic_crs CRS code ", coord_ref_sys_code)





def fill_vertical_crs(proj_db_cursor):
    proj_db_cursor.execute("SELECT data_source, coord_ref_sys_code, coord_ref_sys_name, coord_ref_sys_kind, coord_sys_code, datum_code, deprecated FROM epsg.epsg_coordinatereferencesystem WHERE coord_ref_sys_kind IN ('vertical') AND datum_code IS NOT NULL")
    res = proj_db_cursor.fetchall()
    for (data_source, coord_ref_sys_code, coord_ref_sys_name, coord_ref_sys_kind, coord_sys_code, datum_code, deprecated ) in res:
        datum_authority = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_datum", datum_code)
        coordinate_system_authority = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinatesystem",  coord_sys_code)
        proj_db_cursor.execute("INSERT INTO vertical_crs VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)", (data_source, coord_ref_sys_code, coord_ref_sys_name.strip(), coordinate_system_authority, coord_sys_code, datum_authority.strip(), datum_code, deprecated))
        # proj_db_cursor.execute("INSERT INTO vertical_crs SELECT ?, coord_ref_sys_code, coord_ref_sys_name, NULL, ?, coord_sys_code, ?, datum_code, deprecated FROM epsg.epsg_coordinatereferencesystem WHERE coord_ref_sys_kind IN ('vertical') AND datum_code IS NOT NULL", (data_source.strip(), data_source.strip(), data_source.strip()))

    proj_db_cursor.execute("SELECT * FROM epsg.epsg_coordinatereferencesystem WHERE coord_ref_sys_kind IN ('vertical') AND datum_code IS NULL AND projection_conv_code NOT IN (7812, 7813)")
    res = proj_db_cursor.fetchall()
    for row in res:
        assert False, row

    proj_db_cursor.execute("SELECT * FROM epsg.epsg_coordinatereferencesystem crs1 WHERE crs1.coord_ref_sys_kind IN ('vertical') AND crs1.datum_code IS NULL AND NOT EXISTS (SELECT 1 FROM epsg.epsg_coordinatereferencesystem crs2 WHERE crs2.coord_ref_sys_code = crs1.base_crs_code AND crs2.coord_ref_sys_kind IN ('vertical'))")
    res = proj_db_cursor.fetchall()
    for row in res:
        assert False, row

   # Insert vertical_crs that are based on another one, such as EPSG:8228 that is based on EPSG:5703
    proj_db_cursor.execute("INSERT INTO vertical_crs SELECT ?, crs1.coord_ref_sys_code, crs1.coord_ref_sys_name, NULL, ?, crs1.coord_sys_code, ?, crs2.datum_code, crs1.deprecated FROM epsg.epsg_coordinatereferencesystem crs1 JOIN epsg.epsg_coordinatereferencesystem crs2 ON crs1.base_crs_code = crs2.coord_ref_sys_code WHERE crs1.coord_ref_sys_kind IN ('vertical') AND crs1.datum_code IS NULL AND crs2.datum_code iS NOT NULL", (EPSG_AUTHORITY, EPSG_AUTHORITY, EPSG_AUTHORITY))

    # Extra punishment for EPSG:8051 that is based on EPSG:5715 which is based on EPSG:5714
    proj_db_cursor.execute("INSERT INTO vertical_crs SELECT ?, crs1.coord_ref_sys_code, crs1.coord_ref_sys_name, NULL, ?, crs1.coord_sys_code, ?, crs3.datum_code, crs1.deprecated FROM epsg.epsg_coordinatereferencesystem crs1 JOIN epsg.epsg_coordinatereferencesystem crs2 ON crs1.base_crs_code = crs2.coord_ref_sys_code JOIN epsg.epsg_coordinatereferencesystem crs3 ON crs2.base_crs_code = crs3.coord_ref_sys_code WHERE crs1.coord_ref_sys_kind IN ('vertical') AND crs1.datum_code IS NULL AND crs2.datum_code IS NULL", (EPSG_AUTHORITY, EPSG_AUTHORITY, EPSG_AUTHORITY))


def fill_engineering_crs(proj_db_cursor):
    # Updated to mirror approach used in other queries: derive coordinate system and datum authorities
    # by joining their respective tables instead of injecting EPSG placeholders.
    proj_db_cursor.execute(
        """
        SELECT
            crs.data_source          AS crs_auth_name,     -- 1
            crs.coord_ref_sys_code   AS coord_ref_sys_code,-- 2
            crs.coord_ref_sys_name   AS coord_ref_sys_name,-- 3
            NULL                     AS description,       -- 4
            cs.data_source           AS coord_sys_auth_name,--5
            crs.coord_sys_code       AS coord_sys_code,    -- 6
            d.data_source            AS datum_auth_name,   -- 7
            crs.datum_code           AS datum_code,        -- 8
            crs.deprecated           AS deprecated         -- 9
        FROM epsg.epsg_coordinatereferencesystem crs
        LEFT JOIN epsg.epsg_coordinatesystem cs
               ON crs.coord_sys_code = cs.coord_sys_code
        LEFT JOIN epsg.epsg_datum d
               ON crs.datum_code = d.datum_code
        WHERE crs.coord_ref_sys_kind = 'engineering'
          AND crs.datum_code IS NOT NULL
          AND crs.coord_ref_sys_name NOT LIKE 'EPSG%example%'
          AND crs.coord_ref_sys_name NOT LIKE 'enter here name%'
        """
    )

    for (crs_auth_name, code, name, description, coord_sys_auth_name, coord_sys_code, datum_auth_name, datum_code, deprecated) in proj_db_cursor.fetchall():
        proj_db_cursor.execute(
            "INSERT INTO engineering_crs VALUES (?,?,?,?,?,?,?,?,?)",
            (crs_auth_name, code, name, description, coord_sys_auth_name, coord_sys_code, datum_auth_name, datum_code, deprecated)
        )

    proj_db_cursor.execute("SELECT * FROM epsg.epsg_coordinatereferencesystem crs1 WHERE crs1.coord_ref_sys_kind IN ('engineering') AND crs1.datum_code IS NULL AND NOT EXISTS (SELECT 1 FROM epsg.epsg_coordinatereferencesystem crs2 WHERE crs2.coord_ref_sys_code = crs1.base_crs_code AND crs2.coord_ref_sys_kind IN ('engineering'))")
    res = proj_db_cursor.fetchall()
    for row in res:
        assert False, row


def fill_conversion(proj_db_cursor):

    # TODO? current we deal with point motion operation as transformation in grid_transformation table
    proj_db_cursor.execute(
        "SELECT DISTINCT * FROM epsg.epsg_coordoperation WHERE coord_op_type NOT IN ('conversion', 'transformation', 'concatenated operation', 'point motion operation')")
    res = proj_db_cursor.fetchall()
    if res:
        raise Exception('Found unexpected coord_op_type in epsg_coordoperation: %s' % str(res))

    already_mapped_methods = set()
    trigger_sql = """
CREATE TRIGGER conversion_method_check_insert_trigger
BEFORE INSERT ON conversion
BEGIN
"""

    # 1068 and 1069 are Height Depth Reversal and Change of Vertical Unit
    # In EPSG, there is one generic instance of those as 7812 and 7813 that
    # don't refer to particular CRS, and instances pointing to CRS names
    # The later are imported in the other_transformation table since we recover
    # the source/target CRS names from the transformation name.
    # Method EPSG:9666 'P6 I=J+90 seismic bin grid coordinate operation' requires more than 7 parameters. Not supported by PROJ for now
    # Idem for EPSG:1049 'P6 I=J-90 seismic bin grid coordinate operation'

    # proj_db_cursor.execute("SELECT coord_op_code, coord_op_name, coord_op_method_code, epsg_coordoperation.data_source, coord_op_method_name, epsg_coordoperationmethod.data_source, epsg_coordoperation.deprecated, epsg_coordoperation.remarks FROM epsg.epsg_coordoperation LEFT JOIN epsg.epsg_coordoperationmethod USING (coord_op_method_code) WHERE coord_op_type = 'conversion' AND coord_op_name NOT LIKE '%to DMSH' AND (coord_op_method_code NOT IN (1068, 1069, 9666, 1049, 1102) OR coord_op_code IN (7812,7813))")
    proj_db_cursor.execute("SELECT coord_op_code, coord_op_name, coord_op_method_code, epsg_coordoperation.data_source, coord_op_method_name, epsg_coordoperationmethod.data_source, epsg_coordoperation.deprecated, epsg_coordoperation.remarks FROM epsg.epsg_coordoperation LEFT JOIN epsg.epsg_coordoperationmethod USING (coord_op_method_code) WHERE coord_op_type = 'conversion' AND coord_op_name NOT LIKE '%to DMSH' AND (coord_op_method_code NOT IN (1068, 1069, 9666, 1049) OR coord_op_code IN (7812,7813))")
    for (code, name, method_code, coordoperation_data_source, method_name, coordoperationmethod_data_source, deprecated, remarks) in proj_db_cursor.fetchall():
        expected_order = 1
        max_n_params = 7
        param_auth_name = [None for i in range(max_n_params)]
        param_code = [None for i in range(max_n_params)]
        param_name = [None for i in range(max_n_params)]
        param_value = [None for i in range(max_n_params)]
        param_uom_auth_name = [None for i in range(max_n_params)]
        param_uom_code = [None for i in range(max_n_params)]
        param_uom_type = [None for i in range(max_n_params)]

        iterator = proj_db_cursor.execute("SELECT sort_order, \
                                                  cop.parameter_code, \
                                                  parameter_name, \
                                                  parameter_value, \
                                                  uom_code, \
                                                  uom.unit_of_meas_type, \
                                                  coord_op_code \
                                           FROM epsg_coordoperationparam cop \
                                            LEFT JOIN epsg_coordoperationparamvalue copv \
                                            LEFT JOIN epsg_unitofmeasure uom \
                                            USING (uom_code) \
                                            LEFT JOIN epsg_coordoperationparamusage copu \
                                               ON cop.parameter_code = copv.parameter_code \
                                               AND copu.parameter_code = copv.parameter_code \
                                                WHERE copu.coord_op_method_code = copv.coord_op_method_code \
                                                    AND coord_op_code = ? \
                                                    AND copv.coord_op_method_code = ? \
                                                    ORDER BY sort_order", (code, method_code))
        for (order, parameter_code, parameter_name, parameter_value, uom_code, uom_type, coord_op_code) in iterator:

            # Modified Krovak and Krovak North Oriented: keep only the 7 first parameters
            if order == max_n_params + 1 and method_code in (1042, 1043):
                break
            assert order <= max_n_params, (method_code, method_name, order)
            assert order == expected_order, (code, name, method_code, method_name)
            param_auth_name[order - 1] = coordoperationmethod_data_source
            param_code[order - 1] = parameter_code
            param_name[order - 1] = parameter_name
            param_value[order - 1] = parameter_value
            param_uom_auth_name[order - 1] = coordoperationmethod_data_source if uom_code else None
            param_uom_code[order - 1] = uom_code
            param_uom_type[order - 1] = uom_type
            expected_order += 1

        if method_code not in already_mapped_methods:
            already_mapped_methods.add(method_code)
            trigger_sql += """
    SELECT RAISE(ABORT, 'insert on conversion violates constraint: bad parameters for %(method_name)s')
        WHERE NEW.deprecated != 1 AND NEW.method_auth_name = '%(coordoperationmethod_data_source)s' AND NEW.method_code = '%(method_code)s' AND (NEW.method_name != '%(method_name)s'""" % {'coordoperationmethod_data_source': coordoperationmethod_data_source, 'method_name': method_name, 'method_code' : method_code}
            for i in range(expected_order-1):
                trigger_sql += " OR NEW.param%(n)d_auth_name != '%(coordoperationmethod_data_source)s' OR NEW.param%(n)d_code != '%(code)d' OR NEW.param%(n)d_name != '%(param_name)s'" % {'n': i+1,  'coordoperationmethod_data_source': param_uom_auth_name[i], 'code': param_code[i], 'param_name': param_name[i]}

                if method_name in ('Change of Vertical Unit'):
                    trigger_sql += " OR (NOT((NEW.param%(n)d_value IS NULL AND NEW.param%(n)d_uom_auth_name IS NULL AND NEW.param%(n)d_uom_code IS NULL) OR (NEW.param%(n)d_value IS NOT NULL AND (SELECT type FROM unit_of_measure WHERE auth_name = NEW.param%(n)s_uom_auth_name AND code = NEW.param%(n)s_uom_code) = 'scale')))" % {'n': i+1, 'param_name': param_name[i]}
                else:
                    trigger_sql += " OR NEW.param%(n)d_value IS NULL OR NEW.param%(n)d_uom_auth_name IS NULL OR NEW.param%(n)d_uom_code IS NULL" % {'n': i+1, 'param_name': param_name[i]}

                if param_uom_type[i]:
                    trigger_sql += " OR (SELECT type FROM unit_of_measure WHERE auth_name = NEW.param%(n)s_uom_auth_name AND code = NEW.param%(n)s_uom_code) != '%(uom_type)s'" % {'n': i+1, 'uom_type': param_uom_type[i]}
            for i in range(expected_order-1, max_n_params):
                trigger_sql += " OR NEW.param%(n)d_auth_name IS NOT NULL OR NEW.param%(n)d_code IS NOT NULL OR NEW.param%(n)d_name IS NOT NULL OR NEW.param%(n)d_value IS NOT NULL OR NEW.param%(n)d_uom_auth_name IS NOT NULL OR NEW.param%(n)d_uom_code IS NOT NULL" % {'n': i+1}
            trigger_sql += ");\n"

        arg = (coordoperation_data_source, code, name,
               remarks,
               coordoperationmethod_data_source, method_code, method_name,
               param_auth_name[0], param_code[0], param_name[0],
               param_value[0], param_uom_auth_name[0], param_uom_code[0],
               param_auth_name[1], param_code[1], param_name[1], param_value[1],
               param_uom_auth_name[1], param_uom_code[1], param_auth_name[2],
               param_code[2], param_name[2], param_value[2],
               param_uom_auth_name[2], param_uom_code[2],
               param_auth_name[3], param_code[3], param_name[3], param_value[3],
               param_uom_auth_name[3], param_uom_code[3], param_auth_name[4],
               param_code[4], param_name[4], param_value[4],
               param_uom_auth_name[4], param_uom_code[4], param_auth_name[5],
               param_code[5], param_name[5], param_value[5],
               param_uom_auth_name[5], param_uom_code[5], param_auth_name[6],
               param_code[6], param_name[6], param_value[6],
               param_uom_auth_name[6], param_uom_code[6],
               deprecated)

        if (code == 3000037):
            print("INSERTING INTO conversion table with code %s" % code)
        proj_db_cursor.execute("INSERT INTO conversion VALUES (" +
            "?,?,?, ?, ?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, " +
            "?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?)", arg)

    trigger_sql += "END;";
    #print(trigger_sql)
    proj_db_cursor.execute(trigger_sql)


def fill_projected_crs(proj_db_cursor):
    # proj_db_cursor.execute("SELECT data_source, coord_ref_sys_code, coord_ref_sys_name, coord_sys_code, base_crs_code, projection_conv_code, deprecated FROM epsg.epsg_coordinatereferencesystem WHERE coord_ref_sys_kind IN ('projected')")
    # proj_db_cursor.execute("SELECT ?, coord_ref_sys_code, coord_ref_sys_name, NULL, ?, coord_sys_code, ?, base_crs_code, ?, projection_conv_code, crs.deprecated, co.coord_op_method_code, com.coord_op_method_name FROM epsg.epsg_coordinatereferencesystem crs LEFT JOIN epsg.epsg_coordoperation co ON crs.projection_conv_code = co.coord_op_code LEFT JOIN epsg.epsg_coordoperationmethod com USING (coord_op_method_code) WHERE coord_ref_sys_kind IN ('projected')", (EPSG_AUTHORITY, EPSG_AUTHORITY, EPSG_AUTHORITY, EPSG_AUTHORITY))
    proj_db_cursor.execute("""
        SELECT
            crs.data_source              AS crs_auth_name,          -- 1
            crs.coord_ref_sys_code       AS coord_ref_sys_code,     -- 2
            crs.coord_ref_sys_name       AS coord_ref_sys_name,     -- 3
            NULL                         AS description,            -- 4
            cs.data_source               AS coord_sys_auth_name,    -- 5 (was auth_name1)
            crs.coord_sys_code           AS coord_sys_code,         -- 6
            base.data_source             AS base_crs_auth_name,     -- 7 (was auth_name2)
            crs.base_crs_code            AS base_crs_code,          -- 8
            co.data_source               AS conversion_auth_name,   -- 9 (was auth_name3)
            crs.projection_conv_code     AS projection_conv_code,   --10
            crs.deprecated               AS deprecated,             --11
            co.coord_op_method_code      AS coord_op_method_code,   --12
            com.coord_op_method_name     AS coord_op_method_name    --13
        FROM epsg.epsg_coordinatereferencesystem crs
        LEFT JOIN epsg.epsg_coordinatesystem cs
               ON crs.coord_sys_code = cs.coord_sys_code
        LEFT JOIN epsg.epsg_coordinatereferencesystem base
               ON crs.base_crs_code = base.coord_ref_sys_code
        LEFT JOIN epsg.epsg_coordoperation co
               ON crs.projection_conv_code = co.coord_op_code
        LEFT JOIN epsg.epsg_coordoperationmethod com
               ON co.coord_op_method_code = com.coord_op_method_code
        WHERE crs.coord_ref_sys_kind = 'projected'
    """)


    # for (auth_name, code, name, coordinate_system_code, geodetic_crs_code, conversion_code, deprecated) in proj_db_cursor.fetchall():
    rows = proj_db_cursor.fetchall()
    for (auth_name, code, name, description, coordinate_system_auth_name, coordinate_system_code, geodetic_crs_auth_name, geodetic_crs_code, conversion_auth_name, conversion_code, deprecated, coord_op_method_code, coord_op_method_name) in rows:
        # crs_auth_name = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinatesystem", coordinate_system_code)
        # geodetic_crs_auth_name = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinatereferencesystem", geodetic_crs_code)
        # conversion_auth_name = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordoperation", conversion_code)
        # If skipping some projection methods is needed

        # if code == 9549: # "LTF2004(C)"
        #     print('Skipping EPSG:9549 LTF2004(C) as we do not handle yet projection method EPSG:1102 is "Lambert Conic Conformal (1SP variant B)"')
        #     continue

        if coord_op_method_code in ():
            print(f'Skipping EPSG:{code} {name} as we do not handle yet projection method EPSG:{coord_op_method_code} / {coord_op_method_name}')
            continue
        # proj_db_cursor.execute("SELECT 1 FROM epsg.epsg_coordinatereferencesystem WHERE coord_ref_sys_code = ? AND coord_ref_sys_kind IN ('geographic 2D', 'geographic 3D', 'geocentric')", (geodetic_crs_code,))
        proj_db_cursor.execute("SELECT 1 FROM epsg.epsg_coordinatereferencesystem WHERE coord_ref_sys_code = ? AND coord_ref_sys_kind IN ('geographic 2D', 'geographic 3D', 'geocentric')", (geodetic_crs_code,))
        if proj_db_cursor.fetchone():
            try:
                # proj_db_cursor.execute("INSERT INTO projected_crs VALUES (?,?,?,NULL,?,?,?,?,?,?,NULL,?)", (auth_name, code, name, crs_auth_name, coordinate_system_code, geodetic_crs_auth_name, geodetic_crs_code, conversion_auth_name, conversion_code, deprecated))
                proj_db_cursor.execute("INSERT INTO projected_crs VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?)", (auth_name, code, name, description, coordinate_system_auth_name, coordinate_system_code, geodetic_crs_auth_name, geodetic_crs_code, conversion_auth_name, conversion_code, deprecated))
            except sqlite3.IntegrityError as e:
                print(e)
                print((auth_name, code, name, description, coordinate_system_auth_name, coordinate_system_code, geodetic_crs_auth_name, geodetic_crs_code, conversion_auth_name, conversion_code, deprecated))
                raise

def fill_compound_crs(proj_db_cursor):
    #proj_db_cursor.execute(
    #    "INSERT INTO crs SELECT ?, coord_ref_sys_code, coord_ref_sys_kind FROM epsg.epsg_coordinatereferencesystem WHERE coord_ref_sys_kind IN ('compound')", (EPSG_AUTHORITY,))

    proj_db_cursor.execute("SELECT data_source, coord_ref_sys_code, coord_ref_sys_name, NULL, cmpd_horizcrs_code, cmpd_vertcrs_code, deprecated FROM epsg.epsg_coordinatereferencesystem WHERE coord_ref_sys_kind IN ('compound') AND cmpd_horizcrs_code NOT IN (SELECT coord_ref_sys_code FROM epsg.epsg_coordinatereferencesystem WHERE coord_ref_sys_kind = 'engineering')")
    #authority_cmpd_horizcrs =
    #print("GOT THE AUTH: ", authority_cmpd_horizcrs, " for code: ", cmpd_horizcrs_code)
    for (auth_name, code, name, description, horiz_code, vert_code, deprecated) in proj_db_cursor.fetchall():
        horiz_auth_name =  get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinatereferencesystem", horiz_code)
        vert_auth_name =  get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinatereferencesystem", vert_code)

        try:
            proj_db_cursor.execute("INSERT INTO compound_crs VALUES (?,?,?,?,?,?,?,?,?)", (auth_name, code, name, description, horiz_auth_name, horiz_code, vert_auth_name, vert_code, deprecated))
        except sqlite3.IntegrityError as e:
            print(e)
            print(auth_name, code, name, description, horiz_auth_name, horiz_code, vert_auth_name, vert_code, deprecated)
            raise

def fill_helmert_transformation(proj_db_cursor):
    proj_db_cursor.execute("SELECT coord_op_code, coord_op_name, epsg.epsg_coordoperationmethod.data_source, coord_op_method_code, coord_op_method_name, source_crs_code, target_crs_code, coord_op_accuracy, coord_tfm_version, epsg_coordoperation.data_source, epsg_coordoperation.deprecated, epsg_coordoperation.remarks FROM epsg.epsg_coordoperation LEFT JOIN epsg.epsg_coordoperationmethod USING (coord_op_method_code) WHERE coord_op_type = 'transformation' AND coord_op_method_code IN (1031, 1032, 1033, 1034, 1035, 1037, 1038, 1039, 1053, 1054, 1055, 1056, 1057, 1058, 1061, 1062, 1063, 1065, 1066, 1132, 1133, 1140, 1149, 9603, 9606, 9607, 9636) ")
    # proj_db_cursor.execute("SELECT coord_op_code, coord_op_name, coord_op_method_code, coord_op_method_name, source_crs_code, target_crs_code, coord_op_accuracy, coord_tfm_version, epsg_coordoperation.deprecated, epsg_coordoperation.remarks FROM epsg.epsg_coordoperation LEFT JOIN epsg.epsg_coordoperationmethod USING (coord_op_method_code) WHERE coord_op_type = 'transformation' AND coord_op_method_code IN (1031, 1032, 1033, 1034, 1035, 1037, 1038, 1039, 1053, 1054, 1055, 1056, 1057, 1058, 1061, 1062, 1063, 1065, 1066, 1132, 1133, 1140, 1149, 9603, 9606, 9607, 9636) ")
    for (code, name, method_authority, method_code, method_name, source_crs_code, target_crs_code, coord_op_accuracy, coord_tfm_version, coord_op_data_source, deprecated, remarks) in proj_db_cursor.fetchall():
        expected_order = 1
        max_n_params = 15
        param_auth_name = [None for i in range(max_n_params)]
        param_code = [None for i in range(max_n_params)]
        param_name = [None for i in range(max_n_params)]
        param_value = [None for i in range(max_n_params)]
        param_uom_code = [None for i in range(max_n_params)]

        iterator = proj_db_cursor.execute("SELECT sort_order, cop.parameter_code, parameter_name, cop.data_source,  parameter_value, uom_code from epsg_coordoperationparam cop LEFT JOIN epsg_coordoperationparamvalue copv LEFT JOIN epsg_coordoperationparamusage copu ON cop.parameter_code = copv.parameter_code AND copu.parameter_code = copv.parameter_code WHERE copu.coord_op_method_code = copv.coord_op_method_code AND coord_op_code = ? AND copv.coord_op_method_code = ? ORDER BY sort_order", (code, method_code))
        for (order, parameter_code, parameter_name, parameter_data_source, parameter_value, uom_code) in iterator:
            assert order <= max_n_params
            assert order == expected_order
            param_auth_name[order - 1] = parameter_data_source
            param_code[order - 1] = parameter_code
            param_name[order - 1] = parameter_name
            param_value[order - 1] = parameter_value
            param_uom_code[order - 1] = uom_code
            expected_order += 1
        n_params = expected_order - 1

        if param_value[0] is None and deprecated:
            continue # silently discard non sense deprecated transforms (like EPSG:1076)

        assert param_code[0] == 8605
        assert param_code[1] == 8606
        assert param_code[2] == 8607
        assert param_uom_code[0] == param_uom_code[1]
        assert param_uom_code[0] == param_uom_code[2]
        px = None
        py = None
        pz = None
        pivot_uom_code = None
        if n_params > 3:
            assert param_code[3] == 8608
            assert param_code[4] == 8609
            assert param_code[5] == 8610
            assert param_code[6] == 8611
            assert param_uom_code[3] == param_uom_code[4]
            assert param_uom_code[3] == param_uom_code[5]
            for i in range(7):
                assert param_uom_code[i] is not None

        if n_params == 8: # Time-specific transformation
            assert param_code[7] == 1049, (code, name, param_code[7])
            param_value[14] = param_value[7]
            param_uom_code[14] = param_uom_code[7]
            param_value[7] = None
            param_uom_code[7] = None

        elif n_params == 10: # Molodensky-Badekas
            assert param_code[7] == 8617, (code, name, param_code[7])
            assert param_code[8] == 8618, (code, name, param_code[8])
            assert param_code[9] == 8667, (code, name, param_code[9])
            assert param_uom_code[7] == param_uom_code[8]
            assert param_uom_code[7] == param_uom_code[9]
            px = param_value[7]
            py = param_value[8]
            pz = param_value[9]
            pivot_uom_code = param_uom_code[7]
            param_value[7] = None
            param_uom_code[7] = None
            param_value[8] = None
            param_uom_code[8] = None
            param_value[9] = None
            param_uom_code[9] = None

        elif n_params > 7: # Time-dependant transformation
            assert param_code[7] == 1040, (code, name, param_code[7])
            assert param_code[8] == 1041
            assert param_code[9] == 1042
            assert param_code[10] == 1043
            assert param_code[11] == 1044
            assert param_code[12] == 1045
            assert param_code[13] == 1046
            assert param_code[14] == 1047
            assert param_uom_code[7] == param_uom_code[8]
            assert param_uom_code[7] == param_uom_code[9]
            assert param_uom_code[10] == param_uom_code[11]
            assert param_uom_code[10] == param_uom_code[12]
            for i in range(15):
                assert param_uom_code[i] is not None, (code, name, i, param_name[i])

        source_crs_authority = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinatereferencesystem", source_crs_code)
        target_crs_authority = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinatereferencesystem", target_crs_code)

        arg = (coord_op_data_source, code, name,
               remarks,
               method_authority, method_code, method_name,
               source_crs_authority, source_crs_code,
               target_crs_authority, target_crs_code,
               coord_op_accuracy,
               param_value[0], param_value[1], param_value[2], EPSG_AUTHORITY, param_uom_code[0],
               param_value[3], param_value[4], param_value[5], EPSG_AUTHORITY if param_uom_code[3] else None, param_uom_code[3],
               param_value[6], EPSG_AUTHORITY if param_uom_code[6] else None, param_uom_code[6],
               param_value[7], param_value[8], param_value[9], EPSG_AUTHORITY if param_uom_code[7] else None, param_uom_code[7],
               param_value[10], param_value[11], param_value[12], EPSG_AUTHORITY if param_uom_code[10] else None, param_uom_code[10],
               param_value[13], EPSG_AUTHORITY if param_uom_code[13] else None, param_uom_code[13],
               param_value[14], EPSG_AUTHORITY if param_uom_code[14] else None, param_uom_code[14],
               px, py, pz, EPSG_AUTHORITY if px else None, pivot_uom_code,
               coord_tfm_version,
               deprecated
               )

        proj_db_cursor.execute("INSERT INTO helmert_transformation VALUES (" +
                "?,?,?, ?, ?,?,?, ?,?, ?,?, ?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?,?,?, ?,?)", arg)



def fill_grid_transformation(proj_db_cursor):
    # TODO: Fix such that authority/data source is extracted from epsg datadump
    # proj_db_cursor.execute("SELECT coord_op_code, coord_op_name, coord_op_method_code, coord_op_method_name, source_crs_code, target_crs_code, coord_op_accuracy, coord_tfm_version, epsg_coordoperation.deprecated, epsg_coordoperation.remarks FROM epsg.epsg_coordoperation LEFT JOIN epsg.epsg_coordoperationmethod USING (coord_op_method_code) WHERE coord_op_type IN ('transformation', 'point motion operation') AND (coord_op_method_name LIKE 'Geographic3D to%' OR coord_op_method_name LIKE 'Geog3D to%' OR coord_op_method_name LIKE 'Point motion by grid%' OR coord_op_method_name LIKE 'Vertical Offset by Grid Interpolation%' OR coord_op_method_name IN ('NADCON', 'NADCON5 (2D)', 'NTv1', 'NTv2', 'VERTCON', 'Geocentric translation by Grid Interpolation (IGN)'))")
    proj_db_cursor.execute("SELECT coord_op_code, coord_op_name, coord_op_method_code, coord_op_method_name, source_crs_code, target_crs_code, coord_op_accuracy, coord_tfm_version, epsg_coordoperation.deprecated, epsg_coordoperation.remarks FROM epsg.epsg_coordoperation LEFT JOIN epsg.epsg_coordoperationmethod USING (coord_op_method_code) WHERE coord_op_type IN ('transformation', 'point motion operation') AND coord_op_method_code NOT IN (1131, 1136) AND (coord_op_method_name LIKE 'Geographic3D to%' OR coord_op_method_name LIKE 'Geog3D to%' OR coord_op_method_name LIKE 'Point motion % grid%' OR coord_op_method_name LIKE 'Vertical Offset %rid%' OR coord_op_method_name LIKE 'Geographic3D Offset % velocity %rid%' OR coord_op_method_name IN ('NADCON', 'NADCON5 (2D)', 'NADCON5 (3D)', 'NTv1', 'NTv2', 'VERTCON', 'Geocentric translations (geog2D domain) by grid (IGN)', 'Geocentric translations using NEU velocity grid (gtg)', 'Geocen translations by grid (gtg) & Geocen translations NEU velocities (gtg)', 'New Zealand Deformation Model', 'Cartesian Grid Offsets by TIN Interpolation (JSON)', 'Vertical Offset by TIN Interpolation (JSON)', 'Geographic2D Offsets by TIN Interpolation (JSON)', 'Vertical change by geoid grid difference (NRCan)'))")
    for (code, name, method_code, method_name, source_crs_code, target_crs_code, coord_op_accuracy, coord_tfm_version, deprecated, remarks) in proj_db_cursor.fetchall():
        if code == 10929: # SOPAC deformation model for California v1
            print(f"Skipping transformation {code} ({name})")
            continue

        expected_order = 1
        if method_name == 'Geocentric translations (geog2D domain) by grid (IGN)':
            max_n_params = 3
        elif method_name == 'Geocentric translations using NEU velocity grid (gtg)':
            max_n_params = 4
        elif method_name == 'Geocen translations by grid (gtg) & Geocen translations NEU velocities (gtg)':
            max_n_params = 6
        else:
            max_n_params = 2
        param_auth_name = [None for i in range(max_n_params)]
        param_code = [None for i in range(max_n_params)]
        param_name = [None for i in range(max_n_params)]
        param_value = [None for i in range(max_n_params)]
        param_uom_code = [None for i in range(max_n_params)]

        iterator = proj_db_cursor.execute("SELECT sort_order, cop.parameter_code, parameter_name, parameter_value, param_value_file_ref, uom_code from epsg_coordoperationparam cop LEFT JOIN epsg_coordoperationparamvalue copv LEFT JOIN epsg_coordoperationparamusage copu ON cop.parameter_code = copv.parameter_code AND copu.parameter_code = copv.parameter_code WHERE copu.coord_op_method_code = copv.coord_op_method_code AND coord_op_code = ? AND copv.coord_op_method_code = ? ORDER BY sort_order", (code, method_code))
        first = True
        order_inc = 0
        for (order, parameter_code, parameter_name, parameter_value, param_value_file_ref, uom_code) in iterator:
            if first and order == 0:
                # Some new records have sort_order starting at 0 rather than 1
                # print(code, name, method_code, method_name, param_code, param_name, order)
                order_inc = 1
            order += order_inc
            first = False
            if method_name == "Point motion (geocen domain) using NEU velocity grid (Gravsoft)":
                # We skip the second and third grid
                if order in (2, 3):
                    continue
                # but keep the interpolation CRS
                if order == 4:
                    order = 2
            # NADCON5 lists 3 grids (lat_shift, lon_shift, ellipsoidal_height_shift). Our database
            # can only list 2. Truncate. Not critical as we ultimately have one GeoTIFF
            # grid for the 3 original grids
            if method_name == "NADCON5 (3D)" and order > max_n_params:
                break
            assert order <= max_n_params, (code, name)
            assert order == expected_order, (code, name, method_code, method_name, param_code, param_name, order)
            if parameter_value is not None:
                assert param_value_file_ref is None or len(param_value_file_ref) == 0, (order, parameter_code, parameter_name, parameter_value, param_value_file_ref, uom_code)
            if param_value_file_ref is not None and len(param_value_file_ref) != 0:
                assert parameter_value is None, (order, parameter_code, parameter_name, parameter_value, param_value_file_ref, uom_code)
            param_auth_name[order - 1] = EPSG_AUTHORITY
            param_code[order - 1] = parameter_code
            param_name[order - 1] = parameter_name
            param_value[order - 1] = parameter_value if parameter_value else param_value_file_ref
            param_uom_code[order - 1] = uom_code
            expected_order += 1
        n_params = expected_order - 1

        assert param_code[0] in (1048, 1050, 1063, 1064, 1072, 8656, 8657, 8666, 8732, 8727), (code, param_code[0])

        grid2_param_auth_name = None
        grid2_param_code = None
        grid2_param_name = None
        grid2_value = None
        interpolation_crs_auth_name = None
        interpolation_crs_code = None

        sql_param_auth_name = [None] * 2
        sql_param_code = [None] * 2
        sql_param_name = [None] * 2
        sql_param_value = [None] * 2
        sql_param_uom_auth_name = [None] * 2
        sql_param_uom_code = [None] * 2

        if method_code == 9613: # NADCON
            assert param_code[1] == 8658, param_code[1]
            grid2_param_auth_name = EPSG_AUTHORITY
            grid2_param_code = param_code[1]
            grid2_param_name = param_name[1]
            grid2_value = param_value[1]
        elif method_code in (1074, 1075): # NADCON5 (2D) and NADCON5 (3D)
            assert param_code[1] == 8658, param_code[1]
            grid2_param_auth_name = EPSG_AUTHORITY
            grid2_param_code = param_code[1]
            grid2_param_name = param_name[1]
            grid2_value = param_value[1]
        # 1071: Vertical Offset by Grid Interpolation (NZLVD)
        # 1080: Vertical Offset by Grid Interpolation (BEV AT)
        # 1081: Geographic3D to GravityRelatedHeight (BEV AT)
        # 1083: Geog3D to Geog2D+Vertical (AUSGeoid v2)
        # 1084: Vertical Offset by Grid Interpolation (gtx)
        # 1085: Vertical Offset by Grid Interpolation (asc)
        # 1086: Point motion (geocen domain) using XYZ velocity grid (INADEFORM)
        # 1088: Geog3D to Geog2D+GravityRelatedHeight (gtx)
        # 1089: Geog3D to Geog2D+GravityRelatedHeight (BEV AT)
        # 1090: Geog3D to Geog2D+GravityRelatedHeight (CGG 2013)
        # 1091: Geog3D to Geog2D+GravityRelatedHeight (CI)
        # 1092: Geog3D to Geog2D+GravityRelatedHeight (EGM2008)
        # 1093: Geog3D to Geog2D+GravityRelatedHeight (Gravsoft)
        # 1094: Geog3D to Geog2D+GravityRelatedHeight (IGN1997)
        # 1095: Geog3D to Geog2D+GravityRelatedHeight (IGN2009)
        # 1096: Geog3D to Geog2D+GravityRelatedHeight (OSGM15-Ire)
        # 1097: Geog3D to Geog2D+GravityRelatedHeight (OSGM-GB)
        # 1098: Geog3D to Geog2D+GravityRelatedHeight (SA 2010)
        # 1100: Geog3D to Geog2D+GravityRelatedHeight (PL txt)
        # 1101: Vertical Offset by Grid Interpolation (PL txt)
        # 1103: Geog3D to Geog2D+GravityRelatedHeight (EGM)
        # 1105: Geog3D to Geog2D+GravityRelatedHeight (ITAL2005)
        # 1110: Geog3D to Geog2D+Depth (Gravsoft)
        # 1112: Vertical Offset by Grid Interpolation (NRCan byn)
        # 1113: Vertical Offset by velocity grid (NRCan byn)
        # 1114: Geographic3D Offset by velocity grid (NTv2_Vel)
        # 1115: Geog3D to Geog2D+Depth (txt)
        # 1118: Geog3D to Geog2D+GravityRelatedHeight (ISG)
        # 1120: Point motion (geocen domain) using XYZ velocity grid (BGN)
        # 1122: Geog3D to Geog2D+Depth (gtx)
        # 1124: Geog3D to Geog2D+GravityRelatedHeight (gtg)
        # 1126: Vertical change by geoid grid difference (NRCan)
        # 1135: Geog3D to Geog2D+GravityRelatedHeight (NGS bin)
        # 1137: Vertical Offset by TIN Interpolation (JSON)
        # 1138: Cartesian Grid Offsets by TIN Interpolation (JSON)
        # 1139: Point motion (geocen domain) using NEU velocity grid (Gravsoft)
        # 1141: Point motion by grid (NEU domain) (NTv2_Vel)
        # WARNING: update Transformation::isGeographic3DToGravityRelatedHeight()
        # in src/iso19111/operation/singleoperation.cpp if adding new methods
        elif method_code in (1071, 1080, 1081, 1083, 1084, 1085, 1086, 1088, 1089, 1090, 1091, 1092, 1093, 1094, 1095, 1096, 1097, 1098, 1100, 1101, 1103, 1105, 1110, 1112, 1113, 1114, 1115, 1118, 1120, 1122, 1124, 1126, 1128, 1129, 1135, 1137, 1138, 1139, 1141) and n_params == 2:
            assert param_code[1] == 1048, (code, method_code, param_code[1])
            interpolation_crs_auth_name = EPSG_AUTHORITY
            interpolation_crs_code = str(int(param_value[1])) # needed to avoid codes like XXXX.0
        # 1087: Geocentric translation by Grid Interpolation (IGN)
        elif method_code in (1087, ) and n_params == 3:
            assert param_code[1] == 1048, (code, method_code, param_code[1])
            interpolation_crs_auth_name = EPSG_AUTHORITY
            interpolation_crs_code = str(int(param_value[1])) # needed to avoid codes like XXXX.0
            # ignoring parameter 2 Standard CT code
        elif method_code == 1144 and n_params == 4:
            assert param_code[1] == 1048, (code, method_code, param_code[1])
            interpolation_crs_auth_name = EPSG_AUTHORITY
            interpolation_crs_code = str(int(param_value[1])) # needed to avoid codes like XXXX.0

            iout = 0
            for i in (2, 3):
                if param_value[i] != -999:
                    sql_param_auth_name[iout] = EPSG_AUTHORITY
                    sql_param_code[iout] = param_code[i]
                    sql_param_name[iout] = param_name[i]
                    sql_param_value[iout] = param_value[i]
                    sql_param_uom_auth_name[iout] = EPSG_AUTHORITY
                    sql_param_uom_code[iout] = param_uom_code[i]
                    iout += 1

        elif method_code == 1142 and n_params == 6:
            assert param_code[1] == 1070, (code, method_code, param_code[1])
            interpolation_crs_auth_name = EPSG_AUTHORITY
            interpolation_crs_code = str(int(param_value[1])) # needed to avoid codes like XXXX.0

            assert param_code[3] == 1071, (code, method_code, param_code[3])
            assert param_value[3] == param_value[1]

            grid2_param_auth_name = EPSG_AUTHORITY
            grid2_param_code = param_code[2]
            grid2_param_name = param_name[2]
            grid2_value = param_value[2]

            iout = 0
            for i in (4, 5):
                if param_value[i] != -999:
                    sql_param_auth_name[iout] = EPSG_AUTHORITY
                    sql_param_code[iout] = param_code[i]
                    sql_param_name[iout] = param_name[i]
                    sql_param_value[iout] = param_value[i]
                    sql_param_uom_auth_name[iout] = EPSG_AUTHORITY
                    sql_param_uom_code[iout] = param_uom_code[i]
                    iout += 1

        else:
            assert n_params == 1, (code, name, method_code, n_params)

        arg = (EPSG_AUTHORITY, code, name,
               remarks,
               EPSG_AUTHORITY, method_code, method_name,
               EPSG_AUTHORITY, source_crs_code,
               EPSG_AUTHORITY, target_crs_code,
               coord_op_accuracy,
               EPSG_AUTHORITY, param_code[0], param_name[0], param_value[0],
               grid2_param_auth_name, grid2_param_code, grid2_param_name, grid2_value,
               sql_param_auth_name[0], sql_param_code[0], sql_param_name[0], sql_param_value[0], sql_param_uom_auth_name[0], sql_param_uom_code[0],
               sql_param_auth_name[1], sql_param_code[1], sql_param_name[1], sql_param_value[1], sql_param_uom_auth_name[1], sql_param_uom_code[1],
               interpolation_crs_auth_name, interpolation_crs_code,
               coord_tfm_version,
               deprecated
               )

        #proj_db_cursor.execute("INSERT INTO coordinate_operation VALUES (?,?,'grid_transformation')", (EPSG_AUTHORITY, code))
        try:
            proj_db_cursor.execute('INSERT INTO grid_transformation VALUES (' +
                '?,?,?, ?, ?,?,?, ?,?, ?,?, ?, ?,?,?,?, ?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?, ?,?)', arg)
        except sqlite3.IntegrityError:
            print(arg)
            raise

def fill_other_transformation(proj_db_cursor):
    # TODO: Fix such that all other transformations (custom) get Equinor authority
    # 9601: Longitude rotation
    # 9616: Vertical offset
    # 9618: Geographic2D with Height offsets
    # 9619: Geographic2D offsets
    # 9624: Affine Parametric Transformation
    # 9660: Geographic3D offsets
    # 1131: Geog3D to Geog2D+GravityRelatedHeight
    # 1136: Geographic3D to GravityRelatedHeight
    # 1068: Height Depth Reversal
    # 1069: Change of Vertical Unit

    # proj_db_cursor.execute("SELECT coord_op_code,\
    #                                coord_op_name,\
    #                                epsg_coordoperation.data_source,\
    #                                coord_op_method_code,\
    #                                coord_op_method_name,\
    #                                epsg_coordoperationmethod.data_source,\
    #                                source_crs_code,\
    #                                target_crs_code, \
    #                                coord_op_accuracy, \
    #                                coord_tfm_version,\
    #                                epsg_coordoperation.deprecated,\
    #                                epsg_coordoperation.remarks\
    #                         FROM epsg.epsg_coordoperation LEFT JOIN epsg.epsg_coordoperationmethod USING (coord_op_method_code)\
    #                         WHERE coord_op_method_code IN (9601, 9616, 9618, 9619, 9624, 9660, 1068, 1069, 1046, 1131, 1136, 9621, 9656, 1143)")

    proj_db_cursor.execute("""
        SELECT
            op.coord_op_code,                 -- 1
            op.coord_op_name,                 -- 2
            op.data_source              AS op_auth_name,          -- 3 (ct authority)
            op.coord_op_method_code,         -- 4
            m.coord_op_method_name,          -- 5
            m.data_source               AS method_auth_name,      -- 6 (method authority)
            op.source_crs_code,              -- 7
            src.data_source             AS source_crs_auth_name,  -- 8 (source crs authority)
            op.target_crs_code,              -- 9
            dst.data_source             AS target_crs_auth_name,  --10 (target crs authority)
            op.coord_op_accuracy,            --11
            op.coord_tfm_version,            --12
            op.deprecated,                   --13
            op.remarks                       --14
        FROM epsg.epsg_coordoperation op
        LEFT JOIN epsg.epsg_coordoperationmethod m
               USING (coord_op_method_code)
        LEFT JOIN epsg.epsg_coordinatereferencesystem src
               ON op.source_crs_code = src.coord_ref_sys_code
        LEFT JOIN epsg.epsg_coordinatereferencesystem dst
               ON op.target_crs_code = dst.coord_ref_sys_code
        WHERE op.coord_op_method_code IN
              (9601, 9616, 9618, 9619, 9624, 9660, 1068, 1069, 1046, 1131, 1136, 9621, 9656, 1143)
          AND op.coord_op_code NOT IN (3100002)
    """)


    for (code, name, ct_auth, method_code, method_name, method_auth, source_crs_code, source_crs_auth, target_crs_code, target_crs_auth, coord_op_accuracy, coord_tfm_version, deprecated, remarks) in proj_db_cursor.fetchall():

        # 1068 and 1069 are Height Depth Reversal and Change of Vertical Unit
        # In EPSG, there is one generic instance of those as 7812 and 7813 that
        # don't refer to particular CRS, and instances pointing to CRS names
        # The later are imported in the other_transformation table since we recover
        # the source/target CRS names from the transformation name.
        if method_code in (1068, 1069) and source_crs_code is None and target_crs_code is None:
            parts = name.split(" to ")
            if len(parts) != 2:
                continue

            # Extract source CRS code and authority
            proj_db_cursor.execute("SELECT coord_ref_sys_code, data_source FROM epsg_coordinatereferencesystem WHERE coord_ref_sys_name = ?", (parts[0],))
            source_codes = proj_db_cursor.fetchall()

            # Extract target CRS code and authority
            proj_db_cursor.execute("SELECT coord_ref_sys_code, data_source FROM epsg_coordinatereferencesystem WHERE coord_ref_sys_name = ?", (parts[1],))
            target_codes = proj_db_cursor.fetchall()

            if len(source_codes) != 1 and len(target_codes) != 1:
                continue

            source_crs_auth = source_codes[0][1] # Source CRS authority
            source_crs_code = source_codes[0][0] # Source CRS code
            target_crs_auth = target_codes[0][1] # Target CRS authority
            target_crs_code = target_codes[0][0] # Target CRS code

        expected_order = 1
        max_n_params = 11
        param_auth_name = [None for i in range(max_n_params)]
        param_code = [None for i in range(max_n_params)]
        param_name = [None for i in range(max_n_params)]
        param_value = [None for i in range(max_n_params)]
        param_uom_auth_name = [None for i in range(max_n_params)]
        param_uom_code = [None for i in range(max_n_params)]
        interpolation_crs_auth_name = None
        interpolation_crs_code = None

        grid_param_auth_name = None
        grid_param_code = None
        grid_param_name = None
        grid_name = None

        iterator = proj_db_cursor.execute("SELECT sort_order, cop.parameter_code, parameter_name, parameter_value, param_value_file_ref, uom_code from epsg_coordoperationparam cop LEFT JOIN epsg_coordoperationparamvalue copv LEFT JOIN epsg_coordoperationparamusage copu ON cop.parameter_code = copv.parameter_code AND copu.parameter_code = copv.parameter_code WHERE copu.coord_op_method_code = copv.coord_op_method_code AND coord_op_code = ? AND copv.coord_op_method_code = ? ORDER BY sort_order", (code, method_code))
        for (order, parameter_code, parameter_name, parameter_value, param_value_file_ref, uom_code) in iterator:

            if parameter_value is not None:
                assert param_value_file_ref is None or len(param_value_file_ref) == 0, (order, parameter_code, parameter_name, parameter_value, param_value_file_ref, uom_code)
            if param_value_file_ref is not None and len(param_value_file_ref) != 0:
                assert parameter_value is None, (order, parameter_code, parameter_name, parameter_value, param_value_file_ref, uom_code)

            if method_code == 1143 and order >= 8:
                if order == 8 and parameter_code == 1050:
                    grid_param_auth_name = EPSG_AUTHORITY
                    grid_param_code = parameter_code
                    grid_param_name = parameter_name
                    grid_name = param_value_file_ref
                    continue
                elif order == 9 and parameter_code == 1048:
                    interpolation_crs_auth_name = EPSG_AUTHORITY
                    interpolation_crs_code = str(int(parameter_value)) # needed to avoid codes like XXXX.0
                    continue
                else:
                    order -= 2

            elif method_code == 1046 and order == 6: # Vertical offset and slope
                assert parameter_code == 1037 # EPSG code for Horizontal CRS
                interpolation_crs_auth_name = EPSG_AUTHORITY
                interpolation_crs_code = str(int(parameter_value)) # needed to avoid codes like XXXX.0
                break

            assert order <= max_n_params, (code, name, order, max_n_params)
            assert order == expected_order, (code, name, order, expected_order)

            param_auth_name[order - 1] = EPSG_AUTHORITY
            param_code[order - 1] = parameter_code
            param_name[order - 1] = parameter_name
            param_value[order - 1] = parameter_value
            param_uom_auth_name[order - 1] = EPSG_AUTHORITY
            param_uom_code[order - 1] = uom_code
            expected_order += 1

        arg = (
            ct_auth, # Transformation authority (ct_auth)
            code,
            name,
            remarks,
            method_auth, # Method authority
            method_code,
            method_name,
            source_crs_auth, # Source CRS authority
            source_crs_code,
            target_crs_auth, # Target CRS authority
            target_crs_code,
            coord_op_accuracy,
            param_auth_name[0], param_code[0], param_name[0],
            param_value[0], param_uom_auth_name[0], param_uom_code[0],
            param_auth_name[1], param_code[1], param_name[1], param_value[1],
            param_uom_auth_name[1], param_uom_code[1], param_auth_name[2],
            param_code[2], param_name[2], param_value[2],
            param_uom_auth_name[2], param_uom_code[2],
            param_auth_name[3], param_code[3], param_name[3], param_value[3],
            param_uom_auth_name[3], param_uom_code[3], param_auth_name[4],
            param_code[4], param_name[4], param_value[4],
            param_uom_auth_name[4], param_uom_code[4], param_auth_name[5],
            param_code[5], param_name[5], param_value[5],
            param_uom_auth_name[5], param_uom_code[5], param_auth_name[6],
            param_code[6], param_name[6], param_value[6],
            param_uom_auth_name[6], param_uom_code[6], param_auth_name[7],
            param_code[7], param_name[7], param_value[7],
            param_uom_auth_name[7], param_uom_code[7], param_auth_name[8],
            param_code[8], param_name[8], param_value[8],
            param_uom_auth_name[8], param_uom_code[8],
            grid_param_auth_name,
            grid_param_code,
            grid_param_name,
            grid_name,
            interpolation_crs_auth_name, interpolation_crs_code,
            coord_tfm_version,
            deprecated
               )

        #proj_db_cursor.execute("INSERT INTO coordinate_operation VALUES (?,?,'other_transformation')", (EPSG_AUTHORITY, code))
        # print(arg)
        proj_db_cursor.execute('INSERT INTO other_transformation VALUES (' +
            '?,?,?, ?, ?,?,?, ?,?, ?,?,  ?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ' +
            '?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?, ?,?, ?,?)', arg)

def fill_concatenated_operation(proj_db_cursor):
    proj_db_cursor.execute("SELECT coord_op_code, coord_op_name, epsg_coordoperation.data_source,  coord_op_method_code, coord_op_method_name, source_crs_code, target_crs_code, coord_op_accuracy, coord_tfm_version, epsg_coordoperation.deprecated, epsg_coordoperation.remarks FROM epsg.epsg_coordoperation LEFT JOIN epsg.epsg_coordoperationmethod USING (coord_op_method_code) WHERE coord_op_type = 'concatenated operation'")
    for (code, name, data_source,  method_code, method_name, source_crs_code, target_crs_code,  coord_op_accuracy, coord_tfm_version, deprecated, remarks) in proj_db_cursor.fetchall():
        expected_order = 1
        steps_code = []

        iterator = proj_db_cursor.execute("SELECT op_path_step, single_operation_code FROM epsg_coordoperationpath WHERE concat_operation_code = ? ORDER BY op_path_step", (code,))
        for (order, single_operation_code) in iterator:
            assert order == expected_order
            steps_code.append(single_operation_code)
            expected_order += 1
        n_params = expected_order - 1
        if n_params == 0:  # For example http://www.epsg-registry.org//export.htm?gml=urn:ogc:def:coordinateOperation:EPSG::8658
            continue

        all_steps_exist = True
        for step_code in steps_code:
            proj_db_cursor.execute("SELECT 1 FROM coordinate_operation_with_conversion_view WHERE code = ?", (step_code,))
            if proj_db_cursor.fetchone() is None:
                print('Step of code %d for concatenated_operation %d does not exist' % (step_code, code))
                all_steps_exist = False
                break

        if all_steps_exist:

            auth_name_source_crs = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinatereferencesystem", source_crs_code)
            auth_name_target_crs = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinatereferencesystem", target_crs_code)

            arg = (data_source, code, name,
                remarks,
                auth_name_source_crs, source_crs_code,
                auth_name_target_crs, target_crs_code,
                coord_op_accuracy,
                coord_tfm_version,
                deprecated
                )

            #proj_db_cursor.execute("INSERT INTO coordinate_operation VALUES (?,?,'concatenated_operation')", (EPSG_AUTHORITY, code))
            proj_db_cursor.execute("INSERT INTO concatenated_operation VALUES (" +
            "?,?,?, ?, ?,?, ?,?, ?, ?,?)", arg)

            for i in range(len(steps_code)):
                auth_name = get_authority_from_tablename_and_code(proj_db_cursor, 'epsg_coordoperation', steps_code[i])
                proj_db_cursor.execute("INSERT INTO concatenated_operation_step VALUES (?,?,?,?,?,NULL)", (data_source, code, i+1, auth_name, steps_code[i]))


def fill_alias(proj_db_cursor):
    proj_db_cursor.execute("SELECT DISTINCT object_table_name, object_code, naming_system_code, alias FROM epsg.epsg_alias WHERE object_table_name = 'epsg_datum'")
    for (object_table_name, code, naming_system_code, alt_name) in proj_db_cursor.fetchall():
        authority = get_authority_from_tablename_and_code(proj_db_cursor, 'epsg_datum', code, True)
        naming_system_data_source = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_namingsystem", naming_system_code, True);
        proj_db_cursor.execute('SELECT 1 FROM geodetic_datum WHERE code = ?', (code,))
        if proj_db_cursor.fetchone() is not None:
            proj_db_cursor.execute("INSERT INTO alias_name VALUES ('geodetic_datum', ?,?,?,?)", (authority, code, alt_name, naming_system_data_source))
        else:
            proj_db_cursor.execute('SELECT 1 FROM vertical_datum WHERE code = ?', (code,))
            if proj_db_cursor.fetchone() is not None:
                proj_db_cursor.execute("INSERT INTO alias_name VALUES ('vertical_datum',?,?,?,?)", (authority, code, alt_name, naming_system_data_source))
            else:
                print('Cannot find datum %s:%s in geodetic_datum or vertical_datum, skipping insertion of datum alias "%s" from naming_system with code %s from "%s"' % (authority, code, alt_name, naming_system_code, naming_system_data_source))


    proj_db_cursor.execute("SELECT DISTINCT object_table_name,object_code, naming_system_code, alias FROM epsg.epsg_alias WHERE object_table_name = 'epsg_coordinatereferencesystem'")
    for (object_table_name, code, naming_system_code, alt_name) in proj_db_cursor.fetchall():
        authority = get_authority_from_tablename_and_code(proj_db_cursor, 'epsg_coordinatereferencesystem', code, True)
        naming_system_data_source = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_namingsystem", naming_system_code, True);
        if int(code) > 60000000:
            continue
        proj_db_cursor.execute('SELECT 1 FROM geodetic_crs WHERE code = ?', (code,))
        if proj_db_cursor.fetchone() is not None:
            proj_db_cursor.execute("INSERT INTO alias_name VALUES ('geodetic_crs',?,?,?,?)", (authority, code, alt_name, naming_system_data_source))
            continue

        proj_db_cursor.execute('SELECT 1 FROM projected_crs WHERE code = ?', (code,))
        if proj_db_cursor.fetchone() is not None:
            proj_db_cursor.execute("INSERT INTO alias_name VALUES ('projected_crs',?,?,?,?)", (authority, code, alt_name, naming_system_data_source))
            continue

        proj_db_cursor.execute('SELECT 1 FROM vertical_crs WHERE code = ?', (code,))
        if proj_db_cursor.fetchone() is not None:
            proj_db_cursor.execute("INSERT INTO alias_name VALUES ('vertical_crs',?,?,?,?)", (authority,code, alt_name, naming_system_data_source))
            continue

        proj_db_cursor.execute('SELECT 1 FROM compound_crs WHERE code = ?', (code,))
        if proj_db_cursor.fetchone() is not None:
            proj_db_cursor.execute("INSERT INTO alias_name VALUES ('compound_crs',?,?,?,?)", (authority,code, alt_name, naming_system_data_source))
            continue

        print('Cannot find CRS %s:%s in geodetic_crs, projected_crs, vertical_crs or compound_crs, skipping insertion of crs alias "%s" from naming_system with code %s from "%s"' % (authority, code, alt_name, naming_system_code, naming_system_data_source))


# def find_table(proj_db_cursor, code):
#     for table_name in ('helmert_transformation', 'grid_transformation', 'concatenated_operation', 'geodetic_crs', 'projected_crs', 'vertical_crs', 'compound_crs'):
#         proj_db_cursor.execute('SELECT name FROM %s WHERE code = ?' % table_name, (code,))
#         row = proj_db_cursor.fetchone()
#         if row is not None:
#             return row[0], table_name
#     return None


def find_table(proj_db_cursor, code):
    for table_name in ('helmert_transformation','grid_transformation','other_transformation','concatenated_operation',
                       'geodetic_crs','projected_crs','vertical_crs','compound_crs','engineering_crs'):
        try:
            proj_db_cursor.execute(f'SELECT name FROM {table_name} WHERE code = ?', (code,))
            row = proj_db_cursor.fetchone()
            if row is not None:
                return row[0], table_name
        except sqlite3.OperationalError:
            # Table might not exist (e.g., engineering_crs in older schema) -> ignore
            continue
    return None

def fill_supersession(proj_db_cursor):
    proj_db_cursor.execute("SELECT object_code, superseded_by FROM epsg.epsg_supersession WHERE object_table_name = 'epsg_coordoperation' AND object_code != superseded_by")
    for row in proj_db_cursor.fetchall():
        code, superseded_by = row
        proj_db_cursor.execute('SELECT 1 FROM coordinate_operation_view WHERE code = ?', (code,))
        if proj_db_cursor.fetchone() is None:
            print('Skipping supersession of %d since it has not been imported' % code)
            continue

        src_name, superseded_table_name = find_table(proj_db_cursor, code)
        dst_name, replacement_table_name = find_table(proj_db_cursor, superseded_by)
        assert superseded_table_name, row
        assert replacement_table_name, row
        if superseded_table_name == 'grid_transformation' and replacement_table_name == 'grid_transformation' and src_name.startswith('NAD27 to NAD83'):
            print('Skipping supersession of %d (%s) by %d (%s) because of exception specific to NAD27 to NAD83' % (code, src_name, superseded_by, dst_name))
            continue

        proj_db_cursor.execute("SELECT source_crs_code, target_crs_code FROM epsg_coordoperation WHERE coord_op_code = ?", (code,))
        source_crs_code_superseded, target_crs_code_superseded = proj_db_cursor.fetchone()

        proj_db_cursor.execute("SELECT source_crs_code, target_crs_code FROM epsg_coordoperation WHERE coord_op_code = ?", (superseded_by,))
        source_crs_code_replacement, target_crs_code_replacement = proj_db_cursor.fetchone()
        same_source_target_crs = (source_crs_code_superseded, target_crs_code_superseded) == (source_crs_code_replacement, target_crs_code_replacement)
        proj_db_cursor.execute("INSERT INTO supersession VALUES (?,'EPSG',?,?,'EPSG',?,'EPSG',?)", (superseded_table_name, code, replacement_table_name, superseded_by, same_source_target_crs))

def fill_deprecation(proj_db_cursor):
    proj_db_cursor.execute("SELECT object_code, replaced_by FROM epsg.epsg_deprecation WHERE object_table_name = 'epsg_coordinatereferencesystem' AND object_code != replaced_by")
    for row in proj_db_cursor.fetchall():
        code, replaced_by = row
        proj_db_cursor.execute('SELECT 1 FROM crs_view WHERE code = ?', (code,))
        if proj_db_cursor.fetchone() is None:
            print('Skipping deprecation of %d since it has not been imported' % code)
            continue

        src_name, deprecated_table_name = find_table(proj_db_cursor, code)
        dst_name, replacement_table_name = find_table(proj_db_cursor, replaced_by)
        assert deprecated_table_name, row
        assert replacement_table_name, row
        assert deprecated_table_name == replacement_table_name

        authority = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinatereferencesystem", code)
        replacement_authority = get_authority_from_tablename_and_code(proj_db_cursor, "epsg_coordinatereferencesystem", replaced_by)
        proj_db_cursor.execute("INSERT INTO deprecation VALUES (?,?,?,?,?,?)", (deprecated_table_name, authority, code, replacement_authority, replaced_by, replacement_authority))



def report_non_imported_operations(proj_db_cursor):
    proj_db_cursor.execute("SELECT coord_op_code, coord_op_type, coord_op_name, coord_op_method_code, coord_op_method_name, source_crs_code, target_crs_code, coord_op_accuracy, epsg_coordoperation.deprecated FROM epsg.epsg_coordoperation LEFT JOIN epsg.epsg_coordoperationmethod USING (coord_op_method_code) WHERE coord_op_code NOT IN (SELECT code FROM coordinate_operation_with_conversion_view) AND NOT (coord_op_method_name = 'France geocentric interpolation' AND epsg_coordoperation.deprecated = 1)")
    rows = []
    first = True
    for row in proj_db_cursor.fetchall():
        if first:
            print('Non imported coordinate_operation:')
            first = False
        print('  ' + str(row))
        rows.append(row)
    return rows

epsg_db_conn, epsg_tmp_db_filename = ingest_epsg()

script_dir_name = os.path.dirname(os.path.realpath(__file__))
sql_dir_name = os.path.join(os.path.dirname(script_dir_name), 'data', 'sql')

# proj_db_filename = ':memory:'
proj_db_filename = 'tmp_proj.db'
if os.path.exists(proj_db_filename):
    os.unlink(proj_db_filename)
proj_db_conn = sqlite3.connect(proj_db_filename)
proj_db_cursor = proj_db_conn.cursor()
proj_db_cursor.execute('PRAGMA foreign_keys = 1;')

ingest_sqlite_dump(proj_db_cursor, os.path.join(sql_dir_name, 'proj_db_table_defs.sql'))
proj_db_cursor.execute("INSERT INTO celestial_body VALUES('PROJ', 'EARTH', 'Earth', 6378137.0);")


# A bit messy, but to avoid churn in our existing .sql files, we temporarily
# recreate the original conversion and helmert_transformation tables
# instead of the view in the true database.

proj_db_cursor.execute("""DROP VIEW conversion;""")
proj_db_cursor.execute("""DROP TABLE conversion_table;""")
proj_db_cursor.execute("""CREATE TABLE conversion(
    auth_name TEXT NOT NULL CHECK (length(auth_name) >= 1),
    code TEXT NOT NULL CHECK (length(code) >= 1),
    name TEXT NOT NULL CHECK (length(name) >= 2),

    description TEXT,

    method_auth_name TEXT CHECK (method_auth_name IS NULL OR length(method_auth_name) >= 1),
    method_code TEXT CHECK (method_code IS NULL OR length(method_code) >= 1),
    method_name TEXT,

    param1_auth_name TEXT,
    param1_code TEXT,
    param1_name TEXT,
    param1_value FLOAT,
    param1_uom_auth_name TEXT,
    param1_uom_code TEXT,

    param2_auth_name TEXT,
    param2_code TEXT,
    param2_name TEXT,
    param2_value FLOAT,
    param2_uom_auth_name TEXT,
    param2_uom_code TEXT,

    param3_auth_name TEXT,
    param3_code TEXT,
    param3_name TEXT,
    param3_value FLOAT,
    param3_uom_auth_name TEXT,
    param3_uom_code TEXT,

    param4_auth_name TEXT,
    param4_code TEXT,
    param4_name TEXT,
    param4_value FLOAT,
    param4_uom_auth_name TEXT,
    param4_uom_code TEXT,

    param5_auth_name TEXT,
    param5_code TEXT,
    param5_name TEXT,
    param5_value FLOAT,
    param5_uom_auth_name TEXT,
    param5_uom_code TEXT,

    param6_auth_name TEXT,
    param6_code TEXT,
    param6_name TEXT,
    param6_value FLOAT,
    param6_uom_auth_name TEXT,
    param6_uom_code TEXT,

    param7_auth_name TEXT,
    param7_code TEXT,
    param7_name TEXT,
    param7_value FLOAT,
    param7_uom_auth_name TEXT,
    param7_uom_code TEXT,

    deprecated BOOLEAN NOT NULL CHECK (deprecated IN (0, 1)),

    CONSTRAINT pk_conversion PRIMARY KEY (auth_name, code)
);""")

proj_db_cursor.execute("""DROP VIEW helmert_transformation;""")
proj_db_cursor.execute("""DROP TABLE helmert_transformation_table;""")
proj_db_cursor.execute("""CREATE TABLE helmert_transformation(
    auth_name TEXT NOT NULL CHECK (length(auth_name) >= 1),
    code TEXT NOT NULL CHECK (length(code) >= 1),
    name TEXT NOT NULL CHECK (length(name) >= 2),

    description TEXT,

    method_auth_name TEXT NOT NULL CHECK (length(method_auth_name) >= 1),
    method_code TEXT NOT NULL CHECK (length(method_code) >= 1),
    method_name NOT NULL CHECK (length(method_name) >= 2),

    source_crs_auth_name TEXT NOT NULL,
    source_crs_code TEXT NOT NULL,
    target_crs_auth_name TEXT NOT NULL,
    target_crs_code TEXT NOT NULL,

    accuracy FLOAT CHECK (accuracy >= 0),

    tx FLOAT NOT NULL,
    ty FLOAT NOT NULL,
    tz FLOAT NOT NULL,
    translation_uom_auth_name TEXT NOT NULL,
    translation_uom_code TEXT NOT NULL,
    rx FLOAT,
    ry FLOAT,
    rz FLOAT,
    rotation_uom_auth_name TEXT,
    rotation_uom_code TEXT,
    scale_difference FLOAT,
    scale_difference_uom_auth_name TEXT,
    scale_difference_uom_code TEXT,
    rate_tx FLOAT,
    rate_ty FLOAT,
    rate_tz FLOAT,
    rate_translation_uom_auth_name TEXT,
    rate_translation_uom_code TEXT,
    rate_rx FLOAT,
    rate_ry FLOAT,
    rate_rz FLOAT,
    rate_rotation_uom_auth_name TEXT,
    rate_rotation_uom_code TEXT,
    rate_scale_difference FLOAT,
    rate_scale_difference_uom_auth_name TEXT,
    rate_scale_difference_uom_code TEXT,
    epoch FLOAT,
    epoch_uom_auth_name TEXT,
    epoch_uom_code TEXT,
    px FLOAT, -- Pivot / evaluation point for Molodensky-Badekas
    py FLOAT,
    pz FLOAT,
    pivot_uom_auth_name TEXT,
    pivot_uom_code TEXT,

    operation_version TEXT, -- normally mandatory in OGC Topic 2 but optional here

    deprecated BOOLEAN NOT NULL CHECK (deprecated IN (0, 1)),

    CONSTRAINT pk_helmert_transformation PRIMARY KEY (auth_name, code)
);""")

proj_db_cursor.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name = 'projected_crs'")
for (name, sql) in proj_db_cursor.fetchall():
    proj_db_cursor.execute("DROP TABLE " + name)
    proj_db_cursor.execute(sql.replace('conversion_table', 'conversion'))

proj_db_cursor.execute("SELECT name, sql FROM sqlite_master WHERE type = 'view'")
for (name, sql) in proj_db_cursor.fetchall():
    if 'conversion_table' in sql:
        proj_db_cursor.execute("DROP VIEW " + name)
        proj_db_cursor.execute(sql.replace('conversion_table', 'conversion'))
    elif 'helmert_transformation_table' in sql:
        proj_db_cursor.execute("DROP VIEW " + name)
        proj_db_cursor.execute(sql.replace('helmert_transformation_table', 'helmert_transformation'))

proj_db_cursor = proj_db_conn.cursor()
proj_db_cursor.execute("ATTACH DATABASE '%s' AS epsg;" % epsg_tmp_db_filename)


fill_unit_of_measure(proj_db_cursor)
fill_ellipsoid(proj_db_cursor)
fill_extent(proj_db_cursor)
fill_scope(proj_db_cursor)
fill_prime_meridian(proj_db_cursor)
fill_geodetic_datum(proj_db_cursor)
fill_vertical_datum(proj_db_cursor)
# fill_engineering_datum(proj_db_cursor)
fill_datumensemble(proj_db_cursor)
fill_coordinate_system(proj_db_cursor)
fill_axis(proj_db_cursor)
fill_geodetic_crs(proj_db_cursor)
fill_vertical_crs(proj_db_cursor)
# fill_engineering_crs(proj_db_cursor)
# create_datumensemble_transformations(proj_db_cursor) # feiler på scopet 	40000001
fill_conversion(proj_db_cursor)
fill_projected_crs(proj_db_cursor)
fill_compound_crs(proj_db_cursor)
fill_helmert_transformation(proj_db_cursor)
fill_grid_transformation(proj_db_cursor)
fill_other_transformation(proj_db_cursor)
fill_concatenated_operation(proj_db_cursor)
fill_alias(proj_db_cursor)
fill_supersession(proj_db_cursor)
fill_deprecation(proj_db_cursor)
fill_usage(proj_db_cursor)
non_imported_operations = report_non_imported_operations(proj_db_cursor)

proj_db_cursor.execute("""DROP TABLE builtin_authorities;""")
printSummary()

proj_db_cursor.close()
proj_db_conn.commit()

files = {}

# Dump the generated database and split it one .sql file per table
# except for usage, that we append just after the record that the usage is for

tables_with_usage = ('geodetic_datum', 'vertical_datum', 'geodetic_crs', 'vertical_crs', 'projected_crs', 'compound_crs', 'helmert_transformation', 'grid_transformation', 'other_transformation', 'conversion', 'concatenated_operation')
usages_map = {}
# INSERT INTO "usage" VALUES('EPSG','13089','geodetic_datum','EPSG','1037','EPSG','3340','EPSG','1028');
for line in proj_db_conn.iterdump():
    if line.startswith('INSERT INTO "'):
        table_name = line[len('INSERT INTO "'):]
        table_name = table_name[0:table_name.find('"')]
        if table_name == 'usage':
            _, code, object_table_name, _, object_code, _, _, _, _ = line.split(',')
            object_table_name = object_table_name[1:-1]
            code = code[1:-1]
            if code[0] >= '0' and code[0] <= '9':
                code = int(code)
            object_code = object_code[1:-1]
            if object_code[0] >= '0' and object_code[0] <= '9':
                object_code = int(object_code)
            assert object_table_name in tables_with_usage, line
            key = (object_table_name, object_code)
            if key not in usages_map:
                usages_map[key] = [(code, line)]
            else:
                usages_map[key].append((code, line))



for line in proj_db_conn.iterdump():
    if line.startswith('INSERT INTO "'):
        table_name = line[len('INSERT INTO "'):]
        table_name = table_name[0:table_name.find('"')]
        if table_name == 'usage':
            continue
        if table_name in files:
            f = files[table_name]
        else:
            f = open(os.path.join(sql_dir_name, table_name) + '.sql', 'wb')
            f.write("--- This file has been generated by scripts/build_db.py. DO NOT EDIT !\n\n".encode('UTF-8'))
            files[table_name] = f
        f.write((line + '\n').encode('UTF-8'))

        if table_name in tables_with_usage:
            auth, code = _extract_auth_and_code_from_insert(line)
            if auth is None:
                # Fallback: keep previous (now removed) heuristic if regex unexpectedly fails
                # (Should not happen, but defensive.)
                continue
            # usages_map keys were built with numeric codes cast to int when possible
            key = (table_name, code)
            if key not in usages_map:
                # No usage entries; skip gracefully
                continue
            usages = sorted(usages_map[key])
            for _, l in usages:
                f.write((l + '\n').encode('UTF-8'))



    elif line.startswith('CREATE TRIGGER conversion_method_check_insert_trigger'):
        table_name = 'conversion_triggers'
        if table_name in files:
            f = files[table_name]
        else:
            f = open(os.path.join(sql_dir_name, table_name) + '.sql', 'wb')
            f.write("--- This file has been generated by scripts/build_db.py. DO NOT EDIT !\n\n".encode('UTF-8'))
            files[table_name] = f
        f.write((line + '\n').replace('BEFORE INSERT ON conversion', 'INSTEAD OF INSERT ON conversion').encode('UTF-8'))


with open(os.path.join(sql_dir_name, 'non_imported_operations') + '.sql', 'wb') as f:
    f.write("--- This file has been generated by scripts/build_db.py. DO NOT EDIT !\n\n".encode('UTF-8'))
    for row in non_imported_operations:
        if 'example' not in row[2]:
            f.write(("-- Non-imported: " + str(row) + '\n').encode('UTF-8'))


# for line in proj_db_conn.iterdump():
#     if line.startswith('INSERT INTO "'):
#         table_name = line[len('INSERT INTO "'):]
#         table_name = table_name[0:table_name.find('"')]
#         if table_name == 'usage':
#             _, code, object_table_name, _, object_code, _, _, _, _ = line.split(',')
#             object_table_name = object_table_name[1:-1]
#             code = int(code[1:-1])
#             object_code = int(object_code[1:-1])
#             assert object_table_name in tables_with_usage, line
#             key = (object_table_name, object_code)
#             if key not in usages_map:
#                 usages_map[key] = [(code, line)]
#             else:
#                 usages_map[key].append((code, line))

# for line in proj_db_conn.iterdump():
#     if line.startswith('INSERT INTO "'):
#         table_name = line[len('INSERT INTO "'):]
#         table_name = table_name[0:table_name.find('"')]
#         if table_name == 'usage':
#             continue
#         if table_name in files:
#             f = files[table_name]
#         else:
#             f = open(os.path.join(sql_dir_name, table_name) + '.sql', 'wb')
#             f.write("--- This file has been generated by scripts/build_db.py. DO NOT EDIT !\n\n".encode('UTF-8'))
#             files[table_name] = f
#         f.write((line + '\n').encode('UTF-8'))

#         if table_name in tables_with_usage:
#             sql = "'INSERT INTO %s VALUES '" % table_name
#             sql_length = len(sql)
#             pos = line.find("'EPSG','")
#             if ((pos > sql_length) or (pos == 0)):
#                 # pos = line.find("'EQUINOR','")
#                 pos = line.find(f"'{EQNR_AUTHORITY}',")
#                 assert pos > 0
#                 pos += len(f"'{EQNR_AUTHORITY}',")
#             else:
#                 assert pos > 0
#                 pos += len("'EPSG','")
#             pos_end = line.find("'", pos)
#             code = int(line[pos:pos_end])

#             try:
#                 usages = sorted(usages_map[(table_name, code)])
#                 for _, l in usages:
#                     f.write((l + '\n').encode('UTF-8'))
#             except:
#                 print("Did not find USAGE for %s, %s" % (table_name, code))

#     elif line.startswith('CREATE TRIGGER conversion_method_check_insert_trigger'):
#         table_name = 'conversion_triggers'
#         if table_name in files:
#             f = files[table_name]
#         else:
#             f = open(os.path.join(sql_dir_name, table_name) + '.sql', 'wb')
#             f.write("--- This file has been generated by scripts/build_db.py. DO NOT EDIT !\n\n".encode('UTF-8'))
#             files[table_name] = f
#         f.write((line + '\n').replace('BEFORE INSERT ON conversion', 'INSTEAD OF INSERT ON conversion').encode('UTF-8'))

#f = files['coordinate_operation']
#for row in non_imported_operations:
#    f.write(("--- Non imported: " + str(row) + '\n').encode('UTF-8'))
del files

# Content already in proj_db_table_defs.sql
os.unlink(os.path.join(sql_dir_name, 'celestial_body') + '.sql')

proj_db_conn = None

# Remove EPSG temp database
epsg_db_conn = None
if os.path.exists(epsg_tmp_db_filename):
    os.unlink(epsg_tmp_db_filename)