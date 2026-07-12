from ariadne.core.schema import (
    EpisodeStatus,
    EpisodeVisualizationState,
    to_visualization_episode_state,
)


def test_visualization_states_match_requested_surface():
    assert EpisodeVisualizationState.CREATED.value == "CREATED"
    assert EpisodeVisualizationState.ACTIVE.value == "ACTIVE"
    assert EpisodeVisualizationState.SEALS.value == "SEALS"
    assert EpisodeVisualizationState.CLOSING.value == "CLOSING"
    assert EpisodeVisualizationState.ARCHIVED.value == "ARCHIVED"


def test_to_visualization_episode_state_maps_protocol_statuses():
    assert to_visualization_episode_state(EpisodeStatus.CREATED) == EpisodeVisualizationState.CREATED
    assert to_visualization_episode_state(EpisodeStatus.ACTIVE) == EpisodeVisualizationState.ACTIVE
    assert to_visualization_episode_state(EpisodeStatus.PENDING_HITL) == EpisodeVisualizationState.ACTIVE
    assert to_visualization_episode_state(EpisodeStatus.CRYSTALLIZATION_PENDING) == EpisodeVisualizationState.ACTIVE
    assert to_visualization_episode_state(EpisodeStatus.CRYSTALLIZED) == EpisodeVisualizationState.ACTIVE
    assert to_visualization_episode_state(EpisodeStatus.CLOSING) == EpisodeVisualizationState.CLOSING
    assert to_visualization_episode_state(
        EpisodeStatus.CLOSING_PENDING_SEAL
    ) == EpisodeVisualizationState.CLOSING
    assert to_visualization_episode_state(EpisodeStatus.CLOSED) == EpisodeVisualizationState.SEALS
    assert to_visualization_episode_state(EpisodeStatus.SEALING) == EpisodeVisualizationState.SEALS
    assert to_visualization_episode_state(EpisodeStatus.SEALED) == EpisodeVisualizationState.SEALS
    assert to_visualization_episode_state(EpisodeStatus.ARCHIVED) == EpisodeVisualizationState.ARCHIVED
