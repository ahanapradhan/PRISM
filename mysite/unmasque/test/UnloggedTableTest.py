from mysite.unmasque.src.util.postgres_queries import PostgresQueries


def _queries(schema=None):
    queries = PostgresQueries()
    if schema is not None:
        queries.set_schema(schema)
    return queries


def test_every_working_schema_create_is_unlogged():
    queries = _queries('unmasque')

    statements = [
        queries.create_table_like('unmasque.customer', 'fresh.customer'),
        queries.create_table_as_select_star_from('unmasque.customer', 'fresh.customer'),
        queries.create_table_as_select_star_from_where('unmasque.customer', 'fresh.customer', 'true'),
        queries.create_table_as_select_star_from_limit_1('unmasque.customer', 'fresh.customer'),
        queries.create_table_as_select_star_from_ctid(
            '(0,1)', '(0,0)', 'unmasque.customer', 'unmasque.customer_restore'),
    ]

    for statement in statements:
        assert 'Create unlogged table' in statement


def test_tables_outside_the_working_schema_stay_logged():
    queries = _queries('unmasque')

    statements = [
        queries.create_table_like('fresh.customer_copy', 'fresh.customer'),
        queries.create_table_as_select_star_from('fresh.customer_copy', 'fresh.customer'),
        queries.create_table_as_select_star_from_where('fresh.customer_copy', 'fresh.customer', 'true'),
        queries.create_table_as_select_star_from_limit_1('fresh.customer_copy', 'fresh.customer'),
        queries.create_table_as_select_star_from_ctid(
            '(0,1)', '(0,0)', 'fresh.customer_copy', 'fresh.customer'),
    ]

    for statement in statements:
        assert 'Create unlogged table' not in statement


def test_custom_working_schema_is_respected():
    queries = _queries('work')

    assert 'Create unlogged table' in queries.create_table_like('work.customer', 'fresh.customer')
    assert 'Create unlogged table' not in queries.create_table_like('unmasque.customer', 'fresh.customer')


def test_default_working_schema_is_unlogged():
    queries = _queries()

    assert 'Create unlogged table' in queries.create_table_like('unmasque.customer', 'fresh.customer')
