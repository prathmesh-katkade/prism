"""SQL Lab intermediate-CTE inspection: list a query's named CTEs and rewrite the
query to materialize one of them standalone, for intermediate-result inspection.

Uses sqlglot to parse and rebuild the query's real AST — never unsafe string
splitting. The materialized SQL is handed back to the client to run through the
existing, already-governed /runs execution path (job queue, cancellation, result
limits, provenance) rather than duplicating that machinery here.
"""

from __future__ import annotations

import sqlglot
from fastapi import APIRouter, HTTPException, status
from prism_api_contracts import (
    CteListRequest,
    CteListResponse,
    CteMaterializeRequest,
    CteMaterializeResponse,
    SqlDialect,
)
from prism_sql_lab_runtime import classify_query
from sqlglot import expressions as exp

from .sql_lab import _connection

router = APIRouter(prefix="/api/v1/sql-lab", tags=["sql-lab-ctes"])

_SQLGLOT_DIALECT = {
    SqlDialect.DUCKDB: "duckdb", SqlDialect.MYSQL: "mysql", SqlDialect.POSTGRESQL: "postgres",
    SqlDialect.SQLSERVER: "tsql", SqlDialect.SQLITE: "sqlite",
}


def _parse(sql: str, dialect_name: str) -> exp.Expression:
    classification = classify_query(sql)
    if not classification.is_read_only:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"CTE inspection requires a proven read-only query. {classification.reason}")
    try:
        return sqlglot.parse_one(sql, read=dialect_name)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"The query could not be parsed: {error}") from error


@router.post("/ctes/list", response_model=CteListResponse)
def list_ctes(request: CteListRequest) -> CteListResponse:
    target = _connection(request.connection_id)
    dialect_name = _SQLGLOT_DIALECT.get(target.connection.dialect, "")
    tree = _parse(request.sql, dialect_name)
    with_clause = tree.find(exp.With)
    if with_clause is None:
        return CteListResponse(ctes=[])
    return CteListResponse(ctes=[cte.alias_or_name for cte in with_clause.expressions])


@router.post("/ctes/materialize", response_model=CteMaterializeResponse)
def materialize_cte(request: CteMaterializeRequest) -> CteMaterializeResponse:
    target = _connection(request.connection_id)
    dialect_name = _SQLGLOT_DIALECT.get(target.connection.dialect, "")
    tree = _parse(request.sql, dialect_name)
    with_clause = tree.find(exp.With)
    if with_clause is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This query has no CTEs (no WITH clause) to materialize.")
    ctes = list(with_clause.expressions)
    names = [cte.alias_or_name for cte in ctes]
    if request.cte_name not in names:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"CTE {request.cte_name!r} was not found in this query. Available: {', '.join(names) or 'none'}.")
    index = names.index(request.cte_name)
    # Keep only the CTEs up to and including the target -- later CTEs this one never
    # references are dropped, and anything the target depends on stays intact.
    prefix = [cte.copy() for cte in ctes[: index + 1]]
    materialized = exp.select("*").from_(request.cte_name)
    materialized.set("with_", exp.With(expressions=prefix))
    sql = materialized.sql(dialect=dialect_name)
    if not classify_query(sql).is_read_only:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="The materialized CTE is not a proven read-only query.")
    return CteMaterializeResponse(cte_name=request.cte_name, materialized_sql=sql)
