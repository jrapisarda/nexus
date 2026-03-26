"""Unit tests for nexus_api routers — verifies route registration and structure."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from nexus_api.main import app
from nexus_api.routers import (
    activity,
    agents,
    civilization,
    economy,
    evolution,
    knowledge_graph,
    marketplace,
    objectives,
    observatory,
    reports,
    securities,
    telemetry,
)
from nexus_api.websocket import router as ws_router, ConnectionManager


class TestRouteRegistration:
    """Verify all expected routes are registered on the FastAPI app."""

    def _get_paths(self):
        """Extract (method, path) pairs from the app."""
        paths = []
        for route in app.routes:
            methods = getattr(route, "methods", None)
            path = getattr(route, "path", None)
            if methods and path:
                for m in methods:
                    paths.append((m, path))
            elif path:
                # WebSocket routes don't have methods
                paths.append(("WS", path))
        return paths

    def test_health_endpoint(self):
        paths = self._get_paths()
        assert ("GET", "/health") in paths

    def test_agent_routes(self):
        paths = self._get_paths()
        assert ("GET", "/api/agents") in paths
        assert ("GET", "/api/agents/{persona_id}") in paths

    def test_activity_routes(self):
        paths = self._get_paths()
        assert ("GET", "/api/activity") in paths

    def test_objective_routes(self):
        paths = self._get_paths()
        assert ("GET", "/api/objectives") in paths
        assert ("GET", "/api/objectives/{objective_id}") in paths
        assert ("GET", "/api/objectives/{objective_id}/dag") in paths

    def test_observatory_routes(self):
        paths = self._get_paths()
        assert ("GET", "/api/observatory/overview") in paths
        assert ("GET", "/api/observatory/alerts") in paths
        assert ("GET", "/api/observatory/reviews") in paths
        assert ("GET", "/api/observatory/workload") in paths
        assert ("GET", "/api/observatory/objectives") in paths

    def test_kg_routes(self):
        paths = self._get_paths()
        assert ("GET", "/api/kg/overview") in paths
        assert ("GET", "/api/kg/nodes") in paths
        assert ("GET", "/api/kg/nodes/{node_id}") in paths
        assert ("GET", "/api/kg/edges") in paths
        assert ("GET", "/api/kg/stats") in paths
        assert ("GET", "/api/kg/subgraph") in paths
        assert ("GET", "/api/kg/path") in paths
        assert ("GET", "/api/kg/evidence") in paths
        assert ("GET", "/api/kg/changes") in paths
        assert ("GET", "/api/kg/search") in paths
        assert ("GET", "/api/kg/objectives/search") in paths
        assert ("GET", "/api/kg/findings/search") in paths

    def test_civilization_routes(self):
        paths = self._get_paths()
        assert ("GET", "/api/civilization/overview") in paths
        assert ("GET", "/api/civilization/capabilities") in paths
        assert ("GET", "/api/civilization/challenges") in paths
        assert ("GET", "/api/civilization/scout-health") in paths
        assert ("GET", "/api/civilization/evolution") in paths
        assert ("GET", "/api/civilization/breakers") in paths

    def test_report_routes(self):
        paths = self._get_paths()
        assert ("GET", "/api/reports/questions/{objective_id}") in paths
        assert ("GET", "/api/reports/files/{report_slug:path}") in paths

    def test_kg_finding_response_does_not_backfill_citations_from_source_url(self):
        row = SimpleNamespace(
            finding_id=uuid4(),
            objective_id=uuid4(),
            objective_title="Objective",
            title="Finding",
            finding_type="research",
            status="validated",
            impact_level="routine",
            review_round=1,
            created_at=datetime.now(timezone.utc),
            kg_nodes_created=[],
            kg_edges_created=[],
            structured_data={
                "source_url": "https://example.com/recovered",
                "abstract": "Recovered abstract should not become a citation.",
                "citations": [],
            },
        )

        response = knowledge_graph._finding_row_to_response(row)

        assert response.citations == []

    def test_economy_routes(self):
        paths = self._get_paths()
        assert ("GET", "/api/economy/summary") in paths
        assert ("GET", "/api/economy/ledger") in paths

    def test_marketplace_routes(self):
        paths = self._get_paths()
        assert ("GET", "/api/marketplace/overview") in paths
        assert ("GET", "/api/marketplace/listings") in paths
        assert ("GET", "/api/marketplace/contracts") in paths
        assert ("GET", "/api/marketplace/activity") in paths

    def test_securities_routes(self):
        paths = self._get_paths()
        assert ("GET", "/api/securities/overview") in paths
        assert ("GET", "/api/securities/instruments") in paths
        assert ("GET", "/api/securities/order-book") in paths
        assert ("GET", "/api/securities/trades") in paths
        assert ("GET", "/api/securities/positions") in paths

    def test_telemetry_routes(self):
        paths = self._get_paths()
        assert ("GET", "/api/telemetry/cost") in paths
        assert ("GET", "/api/telemetry/performance") in paths

    def test_evolution_routes(self):
        paths = self._get_paths()
        assert ("GET", "/api/evolution/lineage") in paths

    def test_websocket_route(self):
        paths = self._get_paths()
        assert ("WS", "/ws") in paths


class TestConnectionManager:
    """Test the WebSocket ConnectionManager logic."""

    def test_initial_state(self):
        mgr = ConnectionManager()
        assert mgr.active_count == 0


class TestRouterPrefixes:
    """Verify each router uses the correct prefix."""

    def test_agents_prefix(self):
        assert agents.router.prefix == "/api/agents"

    def test_activity_prefix(self):
        assert activity.router.prefix == "/api/activity"

    def test_civilization_prefix(self):
        assert civilization.router.prefix == "/api/civilization"

    def test_objectives_prefix(self):
        assert objectives.router.prefix == "/api/objectives"

    def test_observatory_prefix(self):
        assert observatory.router.prefix == "/api/observatory"

    def test_kg_prefix(self):
        assert knowledge_graph.router.prefix == "/api/kg"

    def test_economy_prefix(self):
        assert economy.router.prefix == "/api/economy"

    def test_reports_prefix(self):
        assert reports.router.prefix == "/api/reports"

    def test_marketplace_prefix(self):
        assert marketplace.router.prefix == "/api/marketplace"

    def test_securities_prefix(self):
        assert securities.router.prefix == "/api/securities"

    def test_telemetry_prefix(self):
        assert telemetry.router.prefix == "/api/telemetry"

    def test_evolution_prefix(self):
        assert evolution.router.prefix == "/api/evolution"


class TestAppMetadata:
    """Test the FastAPI app configuration."""

    def test_app_title(self):
        assert app.title == "NEXUS Observatory API"

    def test_app_version(self):
        assert app.version == "0.1.0"

    def test_cors_middleware_present(self):
        # CORSMiddleware wraps the app, so check the middleware stack
        middleware_classes = [type(m).__name__ for m in app.user_middleware]
        assert "Middleware" in str(middleware_classes) or len(app.user_middleware) > 0
