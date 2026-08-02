from lakehouse.services.qualitative_label import assign_qualitative_labels


class TestAssignQualitativeLabels:
    def test_top_k_8(self):
        scores = [0.95, 0.90, 0.85, 0.80, 0.60, 0.50, 0.40, 0.30]
        labels = assign_qualitative_labels(scores)
        # top 25% (2): Alta
        # mid 50% (4): Media
        # bottom 25% (2): Baja
        assert labels == ["Alta", "Alta", "Media", "Media", "Media", "Media", "Baja", "Baja"]

    def test_top_k_1(self):
        labels = assign_qualitative_labels([0.42])
        assert labels == ["Alta"]

    def test_top_k_3(self):
        labels = assign_qualitative_labels([0.90, 0.80, 0.30])
        # todos < 4 → todos Alta
        assert labels == ["Alta", "Alta", "Alta"]

    def test_top_k_4(self):
        scores = [0.90, 0.80, 0.70, 0.60]
        labels = assign_qualitative_labels(scores)
        # top 25% (1): Alta
        # mid 50% (2): Media
        # bottom 25% (1): Baja
        assert labels == ["Alta", "Media", "Media", "Baja"]

    def test_identical_scores(self):
        scores = [0.50, 0.50, 0.50, 0.50, 0.50]
        labels = assign_qualitative_labels(scores)
        assert labels == ["Alta", "Media", "Media", "Media", "Baja"]

    def test_empty(self):
        assert assign_qualitative_labels([]) == []
