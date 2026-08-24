import unittest
from sorting_algorithms import bubble_sort, insertion_sort


class TestBubbleSort(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(bubble_sort([3, 1, 2]), [1, 2, 3])

    def test_already_sorted(self):
        self.assertEqual(bubble_sort([1, 2, 3]), [1, 2, 3])

    def test_reverse_sorted(self):
        self.assertEqual(bubble_sort([3, 2, 1]), [1, 2, 3])

    def test_empty(self):
        self.assertEqual(bubble_sort([]), [])

    def test_single_element(self):
        self.assertEqual(bubble_sort([5]), [5])

    def test_does_not_mutate_input(self):
        original = [3, 1, 2]
        result = bubble_sort(original)
        self.assertEqual(original, [3, 1, 2])
        self.assertEqual(result, [1, 2, 3])

    def test_returns_new_list(self):
        original = [3, 1, 2]
        result = bubble_sort(original)
        self.assertIsNot(original, result)


class TestInsertionSort(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(insertion_sort([3, 1, 2]), [1, 2, 3])

    def test_already_sorted(self):
        self.assertEqual(insertion_sort([1, 2, 3]), [1, 2, 3])

    def test_reverse_sorted(self):
        self.assertEqual(insertion_sort([3, 2, 1]), [1, 2, 3])

    def test_empty(self):
        self.assertEqual(insertion_sort([]), [])

    def test_single_element(self):
        self.assertEqual(insertion_sort([5]), [5])

    def test_does_not_mutate_input(self):
        original = [3, 1, 2]
        result = insertion_sort(original)
        self.assertEqual(original, [3, 1, 2])
        self.assertEqual(result, [1, 2, 3])

    def test_returns_new_list(self):
        original = [3, 1, 2]
        result = insertion_sort(original)
        self.assertIsNot(original, result)


if __name__ == '__main__':
    unittest.main()

