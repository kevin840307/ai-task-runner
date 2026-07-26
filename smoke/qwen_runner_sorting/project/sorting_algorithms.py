def bubble_sort(values):
    """
    Sorts a list using the bubble sort algorithm.
    
    Args:
        values: A list of comparable elements
        
    Returns:
        A new list containing the sorted elements in ascending order.
        
    Note:
        Does not mutate the input list.
    """
    result = list(values)
    n = len(result)
    
    for i in range(n):
        swapped = False
        for j in range(0, n - i - 1):
            if result[j] > result[j + 1]:
                result[j], result[j + 1] = result[j + 1], result[j]
                swapped = True
        if not swapped:
            break
            
    return result


def insertion_sort(values):
    """
    Sorts a list using the insertion sort algorithm.
    
    Args:
        values: A list of comparable elements
        
    Returns:
        A new list containing the sorted elements in ascending order.
        
    Note:
        Does not mutate the input list.
    """
    result = list(values)
    n = len(result)
    
    for i in range(1, n):
        key = result[i]
        j = i - 1
        
        while j >= 0 and result[j] > key:
            result[j + 1] = result[j]
            j -= 1
        
        result[j + 1] = key
            
    return result
