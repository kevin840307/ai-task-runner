"""Implementing classic sorting algorithms"""
def bubble_sort(values):
    """Return a new list with values sorted using bubble sort."""
    # Create a copy to avoid mutating input
    result = list(values)
    n = len(result)
    for i in range(n):
        # Last i elements are already in place
        for j in range(0, n - i - 1):
            if result[j] > result[j + 1]:
                # Swap if adjacent elements are in wrong order
                result[j], result[j + 1] = result[j + 1], result[j]
    return result

def insertion_sort(values):
    """Return a new list with values sorted using insertion sort."""
    # Create a copy to avoid mutating input
    result = []
    for item in values:
        # Insert item in sorted position
        result.append(item)
        # Move the item to its correct position
        j = len(result) - 1
        while j > 0 and result[j - 1] > result[j]:
            result[j - 1], result[j] = result[j], result[j - 1]
            j -= 1
    return result