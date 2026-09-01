"""Compatibility re-exports for legacy API schema imports.

New code should import schemas from their domain module in schemas.
"""

from api.schemas.analysis import (
    AnalysisConstraintRow,
    AnalysisConstraintsAvailableResponse,
    AnalysisContributionTerm,
    AnalysisEsspGroupsAvailableResponse,
    AnalysisEsspGroupsUnavailableResponse,
    AnalysisSettlementPointMetadata,
    AnalysisSettlementPointsAvailableResponse,
    BriefDayResponse,
    BriefDetailsResponse,
    BriefHeroShellResponse,
    ChronicElementRow,
    ContextAvailableResponse,
    ContextUnavailableResponse,
    EsspGroup,
    GradeAvailableResponse,
    GradeHalfResponse,
    GradeHistoryAvailableResponse,
    GradeHistoryDayResponse,
    GradeHistoryHalfResponse,
    GradeMetricsResponse,
    GradeSupportResponse,
    HeroAvailableResponse,
    HeroCursor,
    HeroLatestResponse,
    HeroProvenance,
    HeroSegment,
    HeroSegments,
    HeroUnavailableAtHorizonResponse,
    HeroUnavailableResponse,
    NodeAnalysisAvailableResponse,
    NodeAnalysisUnavailableResponse,
    NodeMarketState,
    NodeStandoutRow,
    StandoutRow,
    StandoutsAvailableResponse,
    TopConstraintRow,
    TopConstraintsAvailableResponse,
    TopNodeRow,
    TopNodesAvailableResponse,
    VoltageClassRow,
)
from api.schemas.common import BootstrapSectionStatus
from api.schemas.conditions import (
    ConditionsEntry,
    ConditionsRangeResponse,
    FuelOutage,
    RegionGen,
    ZoneLoad,
)
from api.schemas.forecast import (
    ErcotRangeEntry,
    ErcotRangeResponse,
    ForecastRangeEntry,
    ForecastRangeResponse,
    ForecastSpState,
)
from api.schemas.map import (
    ConstraintReach,
    ExposuresResponse,
    MapMeta,
    MapOverview,
    MapSummaryResponse,
    OverviewConstraint,
    RankedConstraint,
    RankedConstraints,
    ReachSp,
    SpExposure,
)
from api.schemas.matrix import MatrixColumn, MatrixFrame, MatrixRow, MatrixSfValues
from api.schemas.scoreboard import (
    DailyPoint,
    ScoreboardDaily,
    ScoreboardHistory,
    ScoreboardSummaryResponse,
    ScoreboardWeekly,
    ScoreHistoryPoint,
    SourcePooled,
    WeeklyPoint,
    WeeklySplit,
)
