import logging

from openupgradelib import openupgrade

import odoo

_logger = logging.getLogger(__name__)


def load_modules(registry, force_demo=False, status=None, update_module=False):
    with registry.cursor() as cr:
        # create a technical table
        # to track number of rows per table before and after the migration
        if not openupgrade.table_exists(cr, "openupgrade_track_row_count"):
            cr.execute(
                """
                CREATE TABLE IF NOT EXISTS openupgrade_track_row_count (
                    id serial NOT NULL,
                    table_name character varying(128) NOT NULL,
                    old_row_count integer DEFAULT 0,
                    new_row_count integer
                );
                """,
            )
            # update old rows count of all table before running the migration
            cr.execute(
                """
                WITH tbl AS (
                  SELECT table_name
                  FROM information_schema.tables
                  WHERE table_name not like 'pg_%'
                      AND table_name not like 'ir_%'
                      AND table_name not like 'test_%'
                      AND table_name not like '%_test'
                      AND table_name != 'openupgrade_track_row_count'
                      AND table_schema = 'public'
                )
                INSERT INTO openupgrade_track_row_count (table_name, old_row_count)
                SELECT
                  table_name,
                  (xpath('/row/c/text()',
                    query_to_xml(format('select count(*) AS c from %I', table_name),
                    false,
                    true,
                    '')))[1]::text::int AS old_row_count
                FROM tbl;
                """,
            )
        # create a technical table
        # to track res.group per user before and after the migration
        if openupgrade.table_exists(
            cr, "res_groups_users_rel"
        ) and not openupgrade.table_exists(cr, "openupgrade_track_user_group"):
            cr.execute(
                """
                CREATE TABLE IF NOT EXISTS openupgrade_track_user_group (
                    id serial NOT NULL,
                    uid integer NOT NULL,
                    gid integer NOT NULL
                );
                """,
            )
            # update old groups of users before running the migration
            cr.execute(
                """
                INSERT INTO openupgrade_track_user_group (uid, gid)
                SELECT
                  grp_user_rel.uid,
                  grp_user_rel.gid
                FROM res_groups_users_rel grp_user_rel;
                """,
            )

    load_modules._original_method(
        registry,
        force_demo=force_demo,
        status=status,
        update_module=update_module,
    )

    with registry.cursor() as cr:
        # update new number of rows of all table after running the migration
        cr.execute(
            """
            WITH tbl AS (
              SELECT id, table_name
              FROM openupgrade_track_row_count
            )
            UPDATE openupgrade_track_row_count otrc
            SET new_row_count =
              (xpath('/row/c/text()',
                query_to_xml(format('select count(*) AS c from %I', otrc.table_name),
                false,
                true,
                '')))[1]::text::int
            FROM tbl
            WHERE (
                SELECT 1
                FROM information_schema.tables
                WHERE table_name=otrc.table_name
                ) > 0
                AND otrc.id = tbl.id;
            """,
        )
    with registry.cursor() as cr:
        # Report
        cr.execute(
            """
            SELECT table_name, old_row_count, new_row_count
            FROM openupgrade_track_row_count
            WHERE old_row_count != new_row_count
            """,
        )
        result = cr.dictfetchall()
        if bool(result):

            def msg(col1, col2, col3):
                return "%s%s| %s%s| %s%s\n" % (
                    col1,
                    " " * (50 - len(col1)),
                    col2,
                    " " * (15 - len(str(col2))),
                    col3,
                    " " * (15 - len(str(col3))),
                )

            msg_all = msg("Table name", "Old row count", "New row count")
            for r in result:
                msg_all += msg(r["table_name"], r["old_row_count"], r["new_row_count"])
            _logger.warning(
                "The following tables have different number of rows:\n" "%s\n" % msg_all
            )
        # Report
        if openupgrade.table_exists(cr, "openupgrade_track_user_group"):
            cr.execute(
                """
                SELECT uid, array_agg(gid) as gids
                FROM openupgrade_track_user_group
                GROUP BY uid
                """,
            )
            old_groups = cr.dictfetchall()
            cr.execute(
                """
                SELECT uid, array_agg(gid) as gids
                FROM res_groups_users_rel
                GROUP BY uid
                """,
            )
            new_groups = cr.dictfetchall()
            if bool(old_groups) and bool(new_groups):

                def msg(col1, col2, col3, col4):
                    return "%s%s| %s%s| %s%s| %s%s\n" % (
                        col1,
                        " " * (20 - len(col1)),
                        col2,
                        " " * (30 - len(str(col2))),
                        col3,
                        " " * (30 - len(str(col3))),
                        col4,
                        " " * (30 - len(str(col4))),
                    )

                msg_all = msg("Users", "Removed Groups", "Added Groups", "Notes")
                for old_data in old_groups:
                    new_data = [d for d in new_groups if d["uid"] == old_data["uid"]]
                    if not new_data:
                        msg_all += msg(
                            str(old_data["uid"]),
                            "",
                            "",
                            "User has been deleted",
                        )
                        continue
                    removed_grps = list(
                        set(old_data["gids"]) - set(new_data[0]["gids"])
                    )
                    added_grps = list(set(new_data[0]["gids"]) - set(old_data["gids"]))
                    msg_all += msg(
                        str(old_data["uid"]),
                        str(removed_grps),
                        str(added_grps),
                        "",
                    )
                old_users = {d["uid"] for d in old_groups}
                new_users = {d["uid"] for d in new_groups}
                for u in list(old_users - new_users):
                    msg_all += msg(str(u), "", "", "New user")
                _logger.warning(
                    "The following users have different:\n" "%s\n" % msg_all
                )
            cr.execute(
                """
                DROP TABLE IF EXISTS openupgrade_track_row_count;
                DROP TABLE IF EXISTS openupgrade_track_user_group;
                """,
            )


load_modules._original_method = odoo.modules.load_modules
odoo.modules.load_modules = load_modules
