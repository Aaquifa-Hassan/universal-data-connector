import pytest
from app.connectors.crm_connector import CRMConnector
from app.connectors.support_connector import SupportConnector
from app.connectors.analytics_connector import AnalyticsConnector

def test_crm_connector_fetch():
    connector = CRMConnector()
    data = connector.fetch()
    assert isinstance(data, list)
    assert len(data) == 10
    assert "customer_id" in data[0]

def test_support_connector_fetch():
    connector = SupportConnector()
    data = connector.fetch()
    assert isinstance(data, list)
    assert len(data) == 10
    assert "ticket_id" in data[0]

def test_analytics_connector_fetch():
    connector = AnalyticsConnector()
    data = connector.fetch()
    assert isinstance(data, list)
    assert len(data) == 10
    assert "metric_name" in data[0]
