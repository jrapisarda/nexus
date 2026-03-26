"""Unit tests for nexus_core.governance — proposals and voting."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from nexus_core.governance.voting import ProposalOutcome


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_conn():
    """Create a mock async database connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    return conn


# ---------------------------------------------------------------------------
# ProposalOutcome dataclass
# ---------------------------------------------------------------------------

class TestProposalOutcomeDataclass:

    def test_proposal_outcome_dataclass(self):
        pid = uuid4()
        outcome = ProposalOutcome(
            proposal_id=pid,
            approved=True,
            vote_counts={"approve": 3, "reject": 1, "abstain": 0},
            weighted_score=1.5,
            rationale="Approved by majority",
        )
        assert outcome.proposal_id == pid
        assert outcome.approved is True
        assert outcome.vote_counts["approve"] == 3
        assert outcome.weighted_score == 1.5
        assert "Approved" in outcome.rationale

    def test_proposal_outcome_defaults(self):
        pid = uuid4()
        outcome = ProposalOutcome(proposal_id=pid, approved=False)
        assert outcome.vote_counts == {}
        assert outcome.weighted_score == 0.0
        assert outcome.rationale == ""

    def test_proposal_outcome_rejected(self):
        pid = uuid4()
        outcome = ProposalOutcome(
            proposal_id=pid,
            approved=False,
            vote_counts={"approve": 1, "reject": 2, "abstain": 0},
            weighted_score=-0.5,
            rationale="Rejected by majority",
        )
        assert outcome.approved is False
        assert outcome.weighted_score < 0


# ---------------------------------------------------------------------------
# create_proposal
# ---------------------------------------------------------------------------

class TestCreateProposal:

    @patch("nexus_core.governance.proposals.emit_event", new_callable=AsyncMock)
    async def test_create_proposal_returns_uuid(self, mock_emit, mock_conn):
        """create_proposal should return a UUID proposal_id."""
        from nexus_core.governance.proposals import create_proposal

        proposal_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = proposal_id
        mock_conn.execute.return_value = mock_result

        result = await create_proposal(
            conn=mock_conn,
            proposer_id=uuid4(),
            proposal_type="deprecate_persona",
            title="Remove underperformer",
            description="Agent has low fitness",
            rationale="Below survival threshold",
        )

        assert result == proposal_id
        assert mock_conn.execute.call_count >= 1

    @patch("nexus_core.governance.proposals.emit_event", new_callable=AsyncMock)
    async def test_create_proposal_inserts_correct_values(self, mock_emit, mock_conn):
        """The INSERT should carry the correct proposal_type, title, etc."""
        from nexus_core.governance.proposals import create_proposal

        proposer_id = uuid4()
        target_id = uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = uuid4()
        mock_conn.execute.return_value = mock_result

        await create_proposal(
            conn=mock_conn,
            proposer_id=proposer_id,
            proposal_type="rule_change",
            title="Update decay rate",
            description="Change rent decay from 5% to 3%",
            rationale="Economy too deflationary",
            target_persona_id=target_id,
        )

        insert_call = mock_conn.execute.call_args_list[0]
        insert_clause = insert_call[0][0]
        params = insert_clause.compile().params
        assert params["proposed_by_persona_id"] == proposer_id
        assert params["proposal_type"] == "rule_change"
        assert params["title"] == "Update decay rate"
        assert params["target_persona_id"] == target_id
        assert params["status"] == "proposed"

    @patch("nexus_core.governance.proposals.emit_event", new_callable=AsyncMock)
    async def test_create_proposal_emits_event(self, mock_emit, mock_conn):
        from nexus_core.governance.proposals import create_proposal

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = uuid4()
        mock_conn.execute.return_value = mock_result

        await create_proposal(
            conn=mock_conn,
            proposer_id=uuid4(),
            proposal_type="activate_persona",
            title="Test",
            description="desc",
            rationale="reason",
        )

        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][1] == "governance_proposal_created"


# ---------------------------------------------------------------------------
# get_proposal
# ---------------------------------------------------------------------------

class TestGetProposal:

    async def test_get_proposal_found(self, mock_conn):
        from nexus_core.governance.proposals import get_proposal

        proposal_id = uuid4()
        mock_row = MagicMock()
        mock_row._mapping = {
            "proposal_id": proposal_id,
            "status": "proposed",
            "title": "Test Proposal",
        }
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = mock_row
        mock_conn.execute.return_value = mock_result

        result = await get_proposal(mock_conn, proposal_id)
        assert result is not None
        assert result["proposal_id"] == proposal_id
        assert result["status"] == "proposed"

    async def test_get_proposal_not_found(self, mock_conn):
        from nexus_core.governance.proposals import get_proposal

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None
        mock_conn.execute.return_value = mock_result

        result = await get_proposal(mock_conn, uuid4())
        assert result is None


# ---------------------------------------------------------------------------
# update_proposal_status
# ---------------------------------------------------------------------------

class TestUpdateProposalStatus:

    @patch("nexus_core.governance.proposals.emit_event", new_callable=AsyncMock)
    async def test_update_status_calls_execute(self, mock_emit, mock_conn):
        from nexus_core.governance.proposals import update_proposal_status

        proposal_id = uuid4()
        await update_proposal_status(mock_conn, proposal_id, "approved")

        # Should call execute for the update and emit_event
        assert mock_conn.execute.call_count >= 1
        mock_emit.assert_called_once()

    @patch("nexus_core.governance.proposals.emit_event", new_callable=AsyncMock)
    async def test_update_status_emits_correct_event(self, mock_emit, mock_conn):
        from nexus_core.governance.proposals import update_proposal_status

        proposal_id = uuid4()
        await update_proposal_status(mock_conn, proposal_id, "rejected")

        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][1] == "governance_proposal_status_changed"
        assert mock_emit.call_args[1]["payload"]["new_status"] == "rejected"


# ---------------------------------------------------------------------------
# cast_vote
# ---------------------------------------------------------------------------

class TestCastVote:

    @patch("nexus_core.governance.voting.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.governance.voting.update_proposal_status", new_callable=AsyncMock)
    @patch("nexus_core.governance.voting.get_proposal", new_callable=AsyncMock)
    async def test_cast_vote_valid(self, mock_get_proposal, mock_update_status, mock_emit, mock_conn):
        """A valid vote on a proposed proposal should succeed."""
        from nexus_core.governance.voting import cast_vote

        proposal_id = uuid4()
        voter_id = uuid4()
        vote_id = uuid4()

        # Mock get_proposal returns a voteable proposal
        mock_get_proposal.return_value = {
            "proposal_id": proposal_id,
            "status": "proposed",
        }

        # Mock duplicate check: no existing vote
        dup_result = MagicMock()
        dup_result.scalar_one.return_value = 0

        # Mock reputation lookup
        rep_result = MagicMock()
        rep_row = MagicMock()
        rep_row.reputation_score = Decimal("0.800")
        rep_result.one_or_none.return_value = rep_row

        # Mock vote insert
        insert_result = MagicMock()
        insert_result.scalar_one.return_value = vote_id

        mock_conn.execute.side_effect = [dup_result, rep_result, insert_result]

        result = await cast_vote(
            conn=mock_conn,
            proposal_id=proposal_id,
            voter_persona_id=voter_id,
            vote="approve",
            reasoning="Strong proposal",
        )

        assert result == vote_id
        # Should transition proposal from "proposed" to "voting"
        mock_update_status.assert_called_once_with(mock_conn, proposal_id, "voting")

    @patch("nexus_core.governance.voting.get_proposal", new_callable=AsyncMock)
    async def test_cast_vote_invalid_vote_value(self, mock_get_proposal, mock_conn):
        """An invalid vote value should raise ValueError."""
        from nexus_core.governance.voting import cast_vote

        with pytest.raises(ValueError, match="Invalid vote value"):
            await cast_vote(
                conn=mock_conn,
                proposal_id=uuid4(),
                voter_persona_id=uuid4(),
                vote="maybe",
                reasoning="unsure",
            )

    @patch("nexus_core.governance.voting.get_proposal", new_callable=AsyncMock)
    async def test_cast_vote_proposal_not_found(self, mock_get_proposal, mock_conn):
        """Voting on a non-existent proposal should raise ValueError."""
        from nexus_core.governance.voting import cast_vote

        mock_get_proposal.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await cast_vote(
                conn=mock_conn,
                proposal_id=uuid4(),
                voter_persona_id=uuid4(),
                vote="approve",
                reasoning="reason",
            )

    @patch("nexus_core.governance.voting.get_proposal", new_callable=AsyncMock)
    async def test_cast_vote_proposal_not_voteable(self, mock_get_proposal, mock_conn):
        """Voting on an already-executed proposal should raise ValueError."""
        from nexus_core.governance.voting import cast_vote

        mock_get_proposal.return_value = {
            "proposal_id": uuid4(),
            "status": "executed",
        }

        with pytest.raises(ValueError, match="cannot accept votes"):
            await cast_vote(
                conn=mock_conn,
                proposal_id=uuid4(),
                voter_persona_id=uuid4(),
                vote="approve",
                reasoning="reason",
            )

    @patch("nexus_core.governance.voting.get_proposal", new_callable=AsyncMock)
    async def test_cast_vote_duplicate_rejected(self, mock_get_proposal, mock_conn):
        """A persona that already voted should be rejected."""
        from nexus_core.governance.voting import cast_vote

        mock_get_proposal.return_value = {
            "proposal_id": uuid4(),
            "status": "voting",
        }

        # Duplicate check returns count = 1
        dup_result = MagicMock()
        dup_result.scalar_one.return_value = 1
        mock_conn.execute.return_value = dup_result

        with pytest.raises(ValueError, match="already voted"):
            await cast_vote(
                conn=mock_conn,
                proposal_id=uuid4(),
                voter_persona_id=uuid4(),
                vote="reject",
                reasoning="reason",
            )


# ---------------------------------------------------------------------------
# tally_votes
# ---------------------------------------------------------------------------

class TestTallyVotes:

    async def test_tally_votes_weighted_majority_approved(self, mock_conn):
        """Proposal should be approved when weighted approve > weighted reject."""
        from nexus_core.governance.voting import tally_votes

        proposal_id = uuid4()

        # Simulate votes: 2 approves (weight 0.8 each), 1 reject (weight 0.5)
        vote1 = MagicMock()
        vote1.vote = "approve"
        vote1.voter_reputation_weight = Decimal("0.800")

        vote2 = MagicMock()
        vote2.vote = "approve"
        vote2.voter_reputation_weight = Decimal("0.800")

        vote3 = MagicMock()
        vote3.vote = "reject"
        vote3.voter_reputation_weight = Decimal("0.500")

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([vote1, vote2, vote3]))
        mock_conn.execute.return_value = mock_result

        outcome = await tally_votes(mock_conn, proposal_id)

        assert isinstance(outcome, ProposalOutcome)
        assert outcome.approved is True
        # Weighted score = (0.8 + 0.8) - 0.5 = 1.1
        assert outcome.weighted_score == pytest.approx(1.1, abs=0.01)
        assert outcome.vote_counts["approve"] == 2
        assert outcome.vote_counts["reject"] == 1
        assert outcome.vote_counts["abstain"] == 0
        assert "approved" in outcome.rationale.lower()

    async def test_tally_votes_weighted_majority_rejected(self, mock_conn):
        """Proposal should be rejected when weighted reject > weighted approve."""
        from nexus_core.governance.voting import tally_votes

        proposal_id = uuid4()

        vote1 = MagicMock()
        vote1.vote = "approve"
        vote1.voter_reputation_weight = Decimal("0.300")

        vote2 = MagicMock()
        vote2.vote = "reject"
        vote2.voter_reputation_weight = Decimal("0.900")

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([vote1, vote2]))
        mock_conn.execute.return_value = mock_result

        outcome = await tally_votes(mock_conn, proposal_id)

        assert outcome.approved is False
        # Weighted score = 0.3 - 0.9 = -0.6
        assert outcome.weighted_score == pytest.approx(-0.6, abs=0.01)
        assert "rejected" in outcome.rationale.lower()

    async def test_tally_votes_no_votes(self, mock_conn):
        """With no votes, proposal should be rejected."""
        from nexus_core.governance.voting import tally_votes

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_conn.execute.return_value = mock_result

        outcome = await tally_votes(mock_conn, uuid4())

        assert outcome.approved is False
        assert outcome.weighted_score == 0.0
        assert outcome.vote_counts == {"approve": 0, "reject": 0, "abstain": 0}
        assert "No votes" in outcome.rationale

    async def test_tally_votes_abstain_does_not_count(self, mock_conn):
        """Abstentions should not affect the weighted score."""
        from nexus_core.governance.voting import tally_votes

        vote1 = MagicMock()
        vote1.vote = "approve"
        vote1.voter_reputation_weight = Decimal("0.600")

        vote2 = MagicMock()
        vote2.vote = "abstain"
        vote2.voter_reputation_weight = Decimal("0.900")

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([vote1, vote2]))
        mock_conn.execute.return_value = mock_result

        outcome = await tally_votes(mock_conn, uuid4())

        assert outcome.approved is True
        # Only approve contributes: 0.6 - 0 = 0.6
        assert outcome.weighted_score == pytest.approx(0.6, abs=0.01)
        assert outcome.vote_counts["abstain"] == 1

    async def test_tally_votes_default_reputation_weight(self, mock_conn):
        """When voter_reputation_weight is None, default of 0.500 should be used."""
        from nexus_core.governance.voting import tally_votes

        vote1 = MagicMock()
        vote1.vote = "approve"
        vote1.voter_reputation_weight = None  # Should default to 0.500

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([vote1]))
        mock_conn.execute.return_value = mock_result

        outcome = await tally_votes(mock_conn, uuid4())

        assert outcome.approved is True
        assert outcome.weighted_score == pytest.approx(0.5, abs=0.01)

    async def test_tally_votes_tie_is_rejected(self, mock_conn):
        """Equal weighted approve and reject means score=0, which is NOT > 0, so rejected."""
        from nexus_core.governance.voting import tally_votes

        vote1 = MagicMock()
        vote1.vote = "approve"
        vote1.voter_reputation_weight = Decimal("0.700")

        vote2 = MagicMock()
        vote2.vote = "reject"
        vote2.voter_reputation_weight = Decimal("0.700")

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([vote1, vote2]))
        mock_conn.execute.return_value = mock_result

        outcome = await tally_votes(mock_conn, uuid4())

        assert outcome.approved is False
        assert outcome.weighted_score == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# execute_outcome
# ---------------------------------------------------------------------------

class TestExecuteOutcome:

    @patch("nexus_core.governance.voting.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.governance.voting.update_proposal_status", new_callable=AsyncMock)
    @patch("nexus_core.governance.voting.get_proposal", new_callable=AsyncMock)
    async def test_execute_outcome_rejected(self, mock_get, mock_update, mock_emit, mock_conn):
        """Rejected outcome should update status to 'rejected' and emit event."""
        from nexus_core.governance.voting import execute_outcome

        proposal_id = uuid4()
        mock_get.return_value = {
            "proposal_id": proposal_id,
            "proposal_type": "deprecate_persona",
            "title": "Test",
            "description": "desc",
            "rationale": "reason",
            "target_persona_id": uuid4(),
        }

        outcome = ProposalOutcome(
            proposal_id=proposal_id,
            approved=False,
            rationale="Rejected by majority",
        )

        await execute_outcome(mock_conn, proposal_id, outcome)

        mock_update.assert_called_once_with(mock_conn, proposal_id, "rejected")
        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][1] == "governance_proposal_rejected"

    @patch("nexus_core.governance.voting.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.governance.voting.update_proposal_status", new_callable=AsyncMock)
    @patch("nexus_core.governance.voting.get_proposal", new_callable=AsyncMock)
    async def test_execute_outcome_deprecate_persona(self, mock_get, mock_update, mock_emit, mock_conn):
        """Approved deprecate_persona should update persona status to 'deprecated'."""
        from nexus_core.governance.voting import execute_outcome

        proposal_id = uuid4()
        target_persona_id = uuid4()
        mock_get.return_value = {
            "proposal_id": proposal_id,
            "proposal_type": "deprecate_persona",
            "title": "Remove agent",
            "description": "desc",
            "rationale": "reason",
            "target_persona_id": target_persona_id,
        }

        outcome = ProposalOutcome(
            proposal_id=proposal_id,
            approved=True,
            rationale="Approved",
        )

        await execute_outcome(mock_conn, proposal_id, outcome)

        # Should have called conn.execute for the persona update
        assert mock_conn.execute.call_count >= 1
        # Should mark proposal as executed
        mock_update.assert_called_with(mock_conn, proposal_id, "executed")

    @patch("nexus_core.governance.voting.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.governance.voting.update_proposal_status", new_callable=AsyncMock)
    @patch("nexus_core.governance.voting.get_proposal", new_callable=AsyncMock)
    async def test_execute_outcome_activate_persona(self, mock_get, mock_update, mock_emit, mock_conn):
        """Approved activate_persona should update persona status to 'active'."""
        from nexus_core.governance.voting import execute_outcome

        proposal_id = uuid4()
        target_persona_id = uuid4()
        mock_get.return_value = {
            "proposal_id": proposal_id,
            "proposal_type": "activate_persona",
            "title": "Reactivate agent",
            "description": "desc",
            "rationale": "reason",
            "target_persona_id": target_persona_id,
        }

        outcome = ProposalOutcome(
            proposal_id=proposal_id,
            approved=True,
            rationale="Approved",
        )

        await execute_outcome(mock_conn, proposal_id, outcome)

        assert mock_conn.execute.call_count >= 1
        mock_update.assert_called_with(mock_conn, proposal_id, "executed")

    @patch("nexus_core.governance.voting.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.governance.voting.update_proposal_status", new_callable=AsyncMock)
    @patch("nexus_core.governance.voting.get_proposal", new_callable=AsyncMock)
    async def test_execute_outcome_proposal_not_found(self, mock_get, mock_update, mock_emit, mock_conn):
        """If proposal is not found, should return early without error."""
        from nexus_core.governance.voting import execute_outcome

        mock_get.return_value = None

        outcome = ProposalOutcome(
            proposal_id=uuid4(),
            approved=True,
        )

        # Should not raise
        await execute_outcome(mock_conn, uuid4(), outcome)

        mock_update.assert_not_called()
        mock_emit.assert_not_called()

    @patch("nexus_core.governance.voting.emit_event", new_callable=AsyncMock)
    @patch("nexus_core.governance.voting.update_proposal_status", new_callable=AsyncMock)
    @patch("nexus_core.governance.voting.get_proposal", new_callable=AsyncMock)
    async def test_execute_outcome_rule_change_logs_to_memory(self, mock_get, mock_update, mock_emit, mock_conn):
        """Approved rule_change should insert into institutional_memory."""
        from nexus_core.governance.voting import execute_outcome

        proposal_id = uuid4()
        mock_get.return_value = {
            "proposal_id": proposal_id,
            "proposal_type": "rule_change",
            "title": "New rule",
            "description": "Change X to Y",
            "rationale": "Improves fairness",
            "target_persona_id": None,
        }

        outcome = ProposalOutcome(
            proposal_id=proposal_id,
            approved=True,
            rationale="Approved",
        )

        await execute_outcome(mock_conn, proposal_id, outcome)

        # Should have inserted into institutional_memory
        assert mock_conn.execute.call_count >= 1
        mock_update.assert_called_with(mock_conn, proposal_id, "executed")
