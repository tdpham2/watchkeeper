"""Small, application-neutral campaign fixtures."""

import pytest


@pytest.fixture
def campaign_file(tmp_path):
    path = tmp_path / "campaign.toml"
    path.write_text(
        """goal = "Explore a small campaign"
[budget]
node_hours = 1.25
[envelope]
templates = ["example"]
queues = ["debug"]
max_nodes = 1
max_walltime_s = 600
max_concurrent_jobs = 1
max_actions_per_wake = 4
[backend]
kind = "simulated"
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def campaign_directory(tmp_path):
    from watchkeeper.campaign import init_campaign

    init_campaign(tmp_path)
    return tmp_path
