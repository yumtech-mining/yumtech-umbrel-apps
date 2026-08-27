#!/usr/bin/env python3

"""Create the durable pool state required by the bundled mining engine."""

import os

import psycopg2


def connect():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASS"],
        connect_timeout=3,
        application_name="yumtech-database-bootstrap",
    )


def main():
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS effort_state (
                    id SMALLINT PRIMARY KEY,
                    accum_diff DOUBLE PRECISION NOT NULL DEFAULT 0,
                    last_block_height BIGINT NOT NULL DEFAULT 0,
                    last_reset TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT effort_state_singleton CHECK (id = 1)
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO effort_state (id)
                VALUES (1)
                ON CONFLICT (id) DO NOTHING
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS yumtech_dashboard_state (
                    id SMALLINT PRIMARY KEY,
                    all_time_best_share DOUBLE PRECISION NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT yumtech_dashboard_state_singleton CHECK (id = 1)
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO yumtech_dashboard_state (id)
                VALUES (1)
                ON CONFLICT (id) DO NOTHING
                """
            )

            cursor.execute(
                """
                SELECT to_regclass('public.raw_shares') IS NOT NULL,
                       to_regclass('public.blocks') IS NOT NULL,
                       to_regclass('public.miners') IS NOT NULL
                """
            )
            has_raw_shares, has_blocks, has_miners = cursor.fetchone()

            if has_raw_shares:
                since_expression = (
                    "COALESCE((SELECT MAX(found_at) FROM blocks WHERE height > 0), "
                    "'1970-01-01 00:00:00+00'::timestamptz)"
                    if has_blocks
                    else "'1970-01-01 00:00:00+00'::timestamptz"
                )
                cursor.execute(
                    f"""
                    UPDATE effort_state
                    SET accum_diff = GREATEST(
                            accum_diff,
                            COALESCE((
                                SELECT SUM(difficulty)
                                FROM raw_shares
                                WHERE accepted
                                  AND created_at > {since_expression}
                            ), 0)
                        ),
                        updated_at = NOW()
                    WHERE id = 1
                    """
                )

            if has_miners:
                raw_best_expression = (
                    "COALESCE((SELECT MAX(difficulty) FROM raw_shares "
                    "WHERE accepted = TRUE), 0)"
                    if has_raw_shares
                    else "0"
                )
                cursor.execute(
                    f"""
                    UPDATE yumtech_dashboard_state
                    SET all_time_best_share = GREATEST(
                            all_time_best_share,
                            COALESCE((
                                SELECT MAX(best_share_difficulty) FROM miners
                            ), 0),
                            {raw_best_expression}
                        ),
                        updated_at = NOW()
                    WHERE id = 1
                    """
                )

    print("YUMTECH database state is ready.")


if __name__ == "__main__":
    main()
