"""Direct unit tests for the extracted seeAlso helpers.

These were inner closures inside `OntologyService.build_entity_graph` and could
only be exercised through the full BFS path. Module-level extraction lets us
test edge cases (FOLIO restriction encoding, cross-direction lookup, dedup)
without graph construction overhead.
"""

from __future__ import annotations

from rdflib import BNode, Graph, Namespace
from rdflib.namespace import OWL, RDF, RDFS

from ontokit.services.entity_graph_helpers import (
    get_see_also_referrers,
    get_see_also_targets,
)

EX = Namespace("http://example.org/")


def _make_class(g: Graph, *names: str) -> None:
    for name in names:
        g.add((EX[name], RDF.type, OWL.Class))


# ---------------------------------------------------------------------------
# get_see_also_targets
# ---------------------------------------------------------------------------


class TestGetSeeAlsoTargets:
    def test_direct_see_also_triple(self) -> None:
        g = Graph()
        _make_class(g, "A", "B")
        g.add((EX.A, RDFS.seeAlso, EX.B))

        targets = get_see_also_targets(g, EX.A)
        assert targets == [EX.B]

    def test_folio_style_restriction_some_values_from(self) -> None:
        """FOLIO encodes seeAlso as a Restriction inside subClassOf."""
        g = Graph()
        _make_class(g, "A", "B")
        restriction = BNode()
        g.add((EX.A, RDFS.subClassOf, restriction))
        g.add((restriction, RDF.type, OWL.Restriction))
        g.add((restriction, OWL.onProperty, RDFS.seeAlso))
        g.add((restriction, OWL.someValuesFrom, EX.B))

        targets = get_see_also_targets(g, EX.A)
        assert targets == [EX.B]

    def test_folio_style_all_values_from_and_has_value(self) -> None:
        """allValuesFrom and hasValue restrictions are also recognized."""
        g = Graph()
        _make_class(g, "A", "B", "C")
        for val_pred, target in (
            (OWL.allValuesFrom, EX.B),
            (OWL.hasValue, EX.C),
        ):
            r = BNode()
            g.add((EX.A, RDFS.subClassOf, r))
            g.add((r, OWL.onProperty, RDFS.seeAlso))
            g.add((r, val_pred, target))

        targets = get_see_also_targets(g, EX.A)
        assert set(targets) == {EX.B, EX.C}

    def test_dedupes_when_same_target_appears_in_direct_and_restriction(self) -> None:
        g = Graph()
        _make_class(g, "A", "B")
        g.add((EX.A, RDFS.seeAlso, EX.B))
        r = BNode()
        g.add((EX.A, RDFS.subClassOf, r))
        g.add((r, OWL.onProperty, RDFS.seeAlso))
        g.add((r, OWL.someValuesFrom, EX.B))

        targets = get_see_also_targets(g, EX.A)
        assert targets == [EX.B]

    def test_named_superclass_is_not_treated_as_restriction(self) -> None:
        """A named (URIRef) parent must not be misread as a restriction."""
        g = Graph()
        _make_class(g, "Animal", "Dog")
        g.add((EX.Dog, RDFS.subClassOf, EX.Animal))
        g.add((EX.Animal, RDFS.seeAlso, EX.OtherAnimal))

        targets = get_see_also_targets(g, EX.Dog)
        # Animal is a named superclass — its own seeAlso must NOT bubble up
        assert targets == []

    def test_restriction_with_unrelated_property_is_ignored(self) -> None:
        """Only restrictions on rdfs:seeAlso are considered."""
        g = Graph()
        _make_class(g, "A", "B")
        r = BNode()
        g.add((EX.A, RDFS.subClassOf, r))
        g.add((r, OWL.onProperty, EX.someOtherProperty))
        g.add((r, OWL.someValuesFrom, EX.B))

        targets = get_see_also_targets(g, EX.A)
        assert targets == []

    def test_no_see_also_returns_empty(self) -> None:
        g = Graph()
        _make_class(g, "A")

        assert get_see_also_targets(g, EX.A) == []


# ---------------------------------------------------------------------------
# get_see_also_referrers
# ---------------------------------------------------------------------------


class TestGetSeeAlsoReferrers:
    def test_direct_reverse_lookup(self) -> None:
        g = Graph()
        _make_class(g, "A", "B")
        g.add((EX.A, RDFS.seeAlso, EX.B))

        # B is referenced by A
        assert get_see_also_referrers(g, EX.B) == [EX.A]

    def test_restriction_reverse_lookup(self) -> None:
        g = Graph()
        _make_class(g, "A", "B")
        r = BNode()
        g.add((EX.A, RDFS.subClassOf, r))
        g.add((r, OWL.onProperty, RDFS.seeAlso))
        g.add((r, OWL.someValuesFrom, EX.B))

        # B is referenced by A via restriction
        assert get_see_also_referrers(g, EX.B) == [EX.A]

    def test_only_returns_classes(self) -> None:
        """If a referrer subject is not declared as owl:Class, exclude it."""
        g = Graph()
        # Note: NotAClass is not declared as owl:Class
        r = BNode()
        g.add((EX.NotAClass, RDFS.subClassOf, r))
        g.add((r, OWL.onProperty, RDFS.seeAlso))
        g.add((r, OWL.someValuesFrom, EX.Target))

        assert get_see_also_referrers(g, EX.Target) == []

    def test_dedupes_when_same_referrer_appears_multiple_ways(self) -> None:
        g = Graph()
        _make_class(g, "A", "B")
        g.add((EX.A, RDFS.seeAlso, EX.B))
        r = BNode()
        g.add((EX.A, RDFS.subClassOf, r))
        g.add((r, OWL.onProperty, RDFS.seeAlso))
        g.add((r, OWL.someValuesFrom, EX.B))

        assert get_see_also_referrers(g, EX.B) == [EX.A]

    def test_no_referrers_returns_empty(self) -> None:
        g = Graph()
        _make_class(g, "A")

        assert get_see_also_referrers(g, EX.A) == []
