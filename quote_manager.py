import os
import csv
import random
from PIL import ImageDraw, ImageFont

QUOTES_DIR = os.path.join('uploads', 'quotes')
os.makedirs(QUOTES_DIR, exist_ok=True)

def wrap_text_by_pixels(text, font, max_width, draw):
    """Wraps text into lines based on the actual pixel width of the rendered font."""
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        test_line = f"{current_line} {word}".strip()
        # draw.textlength returns the width of the string in pixels
        if draw.textlength(test_line, font=font) <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines

def calculate_best_fit(quote_text, author, draw, max_width=720, max_height=360):
    """
    Iteratively shrinks the font size until the wrapped text and author fit in the bounding box.
    Returns (lines, quote_font, author_font, line_height) or Nones if it absolutely won't fit.
    """
    max_font_size = 72
    min_font_size = 24

    for size in range(max_font_size, min_font_size - 1, -4):
        try:
            # You can point this to your specific font paths
            font_quote = ImageFont.truetype("fonts/roboto/Roboto-Regular.ttf", size)
            font_author = ImageFont.truetype("fonts/roboto/Roboto-Black.ttf", max(20, size - 12))
        except Exception:
            font_quote = font_author = ImageFont.load_default()

        lines = wrap_text_by_pixels(quote_text, font_quote, max_width, draw)
        
        # Approximate line height is usually 1.2x the font size
        line_height = size * 1.2
        
        # Total height = (Number of lines * line height) + (Blank space) + (Author text height)
        total_height = (len(lines) * line_height) + (size * 1.5) 
        
        if total_height <= max_height:
            return lines, font_quote, font_author, line_height
            
    # If it finishes the loop and still doesn't fit, it's too long!
    return None, None, None, None

def get_next_quote(state, draw):
    """
    Reads the active CSV, filters out shown quotes, picks a random one,
    and calculates the layout. If it doesn't fit, it tries the next one.
    """
    active_csv = state.get('active_quote_csv')
    if not active_csv:
        return {"error": "No active CSV selected in Web UI."}
        
    csv_path = os.path.join(QUOTES_DIR, active_csv)
    if not os.path.exists(csv_path):
        return {"error": f"CSV '{active_csv}' not found."}

    # 1. Read the CSV (Expects columns: id, person, quote)
    all_quotes = []
    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                all_quotes.append(row)
    except Exception as e:
        return {"error": f"Error reading CSV: {e}"}

    if not all_quotes:
        return {"error": "CSV is empty."}

    # 2. Filter out already shown quotes
    shown_ids = state.get('shown_quotes', [])
    available_quotes = [q for q in all_quotes if q.get('id') not in shown_ids]

    # If we've shown everything, reset the list!
    if not available_quotes:
        shown_ids = []
        available_quotes = all_quotes

    # 3. Pick a random quote and test if it fits
    random.shuffle(available_quotes)
    
    for selected in available_quotes:
        text = selected.get('quote', '')
        author = selected.get('person', 'Unknown')
        
        lines, font_q, font_a, lh = calculate_best_fit(text, author, draw)
        
        if lines: # We found a fit!
            # Update the state with the newly shown ID
            shown_ids.append(selected.get('id'))
            state['shown_quotes'] = shown_ids
            
            return {
                "lines": lines,
                "author": author,
                "font_quote": font_q,
                "font_author": font_a,
                "line_height": lh
            }
            
        else:
            print(f"[*] Skipping quote ID {selected.get('id')} - Too long to fit.")
            # Add to shown_ids so we don't infinitely retry it later
            shown_ids.append(selected.get('id'))
            
    # If we looped through the entire shuffled list and NOTHING fit
    return {"error": "All remaining quotes are too long for the screen."}