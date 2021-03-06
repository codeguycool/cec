# -*-coding: utf-8 -*-
""" PostgreSQL client.
"""

# 3rd party library
import psycopg2
import psycopg2.extras

# app module
from framework.err import ERR_DB_QUERY, ERR_DB_TIME_OUT, RequestError
from framework.sys_var import (
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD,
    KARAOKE_DB_HOST, KARAOKE_DB_PORT, KARAOKE_DB_NAME, KARAOKE_DB_USER, KARAOKE_DB_PASSWORD,
    AV_DB_HOST, AV_DB_PORT, AV_DB_NAME, AV_DB_USER, AV_DB_PASSWORD,
    FILE_DB_HOST, FILE_DB_PORT, FILE_DB_NAME, FILE_DB_USER, FILE_DB_PASSWORD,
    DB_QUERY_TIMEOUT
)


class PGClient(object):
    db_list = {
        'movie': {
            'dbname': DB_NAME,
            'user': DB_USER,
            'password': DB_PASSWORD,
            'host': DB_HOST,
            'port': DB_PORT
        },
        'karaoke': {
            'dbname': KARAOKE_DB_NAME,
            'user': KARAOKE_DB_USER,
            'password': KARAOKE_DB_PASSWORD,
            'host': KARAOKE_DB_HOST,
            'port': KARAOKE_DB_PORT
        },
        'av': {
            'dbname': AV_DB_NAME,
            'user': AV_DB_USER,
            'password': AV_DB_PASSWORD,
            'host': AV_DB_HOST,
            'port': AV_DB_PORT
        },
        'file': {
            'dbname': FILE_DB_NAME,
            'user': FILE_DB_USER,
            'password': FILE_DB_PASSWORD,
            'host': FILE_DB_HOST,
            'port': FILE_DB_PORT
        }
    }

    def __init__(self, db='movie', timeout=True):
        """
        [Arguments]
            db: str
                Target database to connect.
        """
        db_setting = PGClient.db_list[db]
        self.conn = psycopg2.connect(**db_setting)
        self.cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        if timeout:
            # Fix for occupy connection issue: Set timeout to each query statement of this connection.
            self.cur.execute("SET statement_timeout = '%s'" % DB_QUERY_TIMEOUT)  # cost 0.07~0.08 second.

    def __del__(self):
        """Close all database connection.
        """
        if not self.cur.closed:
            self.cur.close()

        if not self.conn.closed:
            self.conn.close()

    def copy_from(self, fileobj, table, sep='\t', null='\\N', size=8192, columns=None):
        try:
            self.cur.copy_from(fileobj, table, sep, null, size, columns)
            return self.cur
        except Exception, e:
            self.conn.rollback()
            # TODO: write log if we need.
            raise RequestError(ERR_DB_QUERY)

    def execute(self, cmd, data=None):
        """Basic database query method.

        [Arguments]
            cmd: str
                All SQL statment that you can input.

            data: dict (optional)
                Pass data separately with dict.

        [Return]
            cur: cursor instance.
        """
        try:
            if data:
                self.cur.execute(cmd, data)
            else:
                self.cur.execute(cmd)

            return self.cur
        except psycopg2.extensions.QueryCanceledError:
            self.conn.rollback()
            raise RequestError(ERR_DB_TIME_OUT)
        except Exception, e:
            self.conn.rollback()
            # TODO: write log if we need.
            raise RequestError(ERR_DB_QUERY)

    def insert(self, table, data, else_sql=None):
        """Packing command for insert data.

        [Arguments]
            table: str
                Table name.

            data: dict
                Insert data information.
                [Example]
                    {'oid': 10, 'tsid': 123, 'type': 'video', ...}

            else_sql: str (optional)
                Other else SQL statment.

        [Return]
            cur: cursor instance.
        """
        # handle args
        field_names = []
        data_keys = []

        for key in data:
            field_names.append(key)
            data_keys.append("%(" + key + ")s")

        else_fmt = else_sql if else_sql else ''

        # excute command
        sql = "INSERT INTO %s(%s) VALUES (%s) %s;" % (table, ', '.join(field_names), ', '.join(data_keys), else_fmt)

        return self.execute(sql, data)

    def query(self, table, fields=None, condition=[], ret_type=None, else_sql=None):
        """Packing command for query data.

        [Arguments]
            table: str
                Table name.

            fields: list (optional)
                Specify query fields, default is select all fields.

            condition: list (optional)
                Query condition.
                [Example]
                    1) ['pid=%(pid)s and oid=%(oid)s', {'oid': 2, 'pid': 1}]
                    2) ["type='post'"]

            ret_type: "all"/None (optional)
                Return value type, you can fetch all result directly.

            else_sql: str
                Other else SQL statment.

        [Return] (cur/data, row_count)
            cur: cursor instance.

            data: list
                Row data in list.

            row_count: int
                Row count of query result.
        """
        # handle args
        if fields:
            fields_fmt = '%s' % ','.join(fields)
        else:
            fields_fmt = '*'

        cond_fmt, cond_data = self._unpack_condition(*condition)
        else_fmt = else_sql if else_sql else ''

        # excute command
        sql = "SELECT %s FROM %s %s %s;" % (fields_fmt, table, cond_fmt, else_fmt)

        if cond_data:
            cur = self.execute(sql, cond_data)
        else:
            cur = self.execute(sql)

        # optional feature
        if ret_type == "all":
            return cur.fetchall(), self.cur.rowcount
        return cur, self.cur.rowcount

    def update(self, table, data, condition=[], else_sql=None):
        """Packing command for update data.

        [Arguments]
            table: str
                Table name.

            data: dict
                Update data information.
                example:
                    {'oid': 10, 'tsid': 123, 'type': 'video', ...}

            condition: list (optional)
                Update condition.
                example:
                    ['tsid=%(tsid)s', {'tsid': 1}]

            else_sql: str (optional)
                Other else SQL statment.

        [Return]
            cur: cursor instance.
        """
        # handle args
        update_list = []

        for key in data:
            update_item = "{0}=%({0})s".format(key)
            update_list.append(update_item)

        cond_fmt, cond_data = self._unpack_condition(*condition)
        sql_data = dict(data, **cond_data)
        else_fmt = else_sql if else_sql else ''

        # excute command
        sql = "UPDATE %s SET %s %s %s;" % (table, ",".join(update_list), cond_fmt, else_fmt)

        if sql_data:
            return self.execute(sql, sql_data)
        return self.execute(sql)

    def remove(self, table, condition=[], else_sql=None):
        """Packing command for delete data.

        [Arguments]
            table: str
                Table name.

            condition: list (optional)
                Remove data condition.
                example:
                    ['tsid=%(tsid)s', {'tsid': 1}]

            else_sql: str (optional)
                Other else SQL statment.

        [Return]
            cur: cursor instance.
        """
        # handle args
        cond_fmt, cond_data = self._unpack_condition(*condition)
        else_fmt = else_sql if else_sql else ''

        # excute command
        sql = "DELETE FROM %s %s %s;" % (table, cond_fmt, else_fmt)

        if cond_data:
            return self.execute(sql, cond_data)
        return self.execute(sql)

    def commit(self):
        self.conn.commit()

    def _unpack_condition(self, sql='', data={}):
        """A tool to handle input arg "condition" of DB query method. 

        [Arguments]
            sql: str
                Condition string from first item of input argument "condition".

            data: dict
                Condition data from second item of input argument "condition".

        [Return]
            sql_str: string
                SQL condition part statment.
        """
        return 'WHERE %s' % sql if sql else sql, data
