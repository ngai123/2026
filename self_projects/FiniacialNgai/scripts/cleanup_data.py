#!/usr/bin/env python3
"""
Clean up and fix the imported financial data.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.repository import list_pnl_periods, get_pnl_by_period, save_pnl

def fix_categorization():
    """Fix any remaining generic categorizations."""
    periods = ['2025-08', '2025-09', '2025-10', '2025-11', '2025-12', '2026-01', '2026-02', '2026-03']

    for period in periods:
        pnl = get_pnl_by_period(period)
        if not pnl:
            continue

        needs_update = False
        updated_income = []
        updated_expense = []

        # Fix income categorization
        for item in pnl['income_items']:
            fixed_item = item.copy()
            desc_lower = item['description'].lower()

            if item['category'] in ['Income', 'Other Income', 'Other']:
                if 'gambling' in desc_lower:
                    fixed_item['category'] = 'Gambling'
                elif 'grant' in desc_lower:
                    fixed_item['category'] = 'Grants/Scholarships'
                elif 'hackathon' in desc_lower or 'prize' in desc_lower:
                    fixed_item['category'] = 'Competitions/Prizes'
                elif 'mummy' in desc_lower or 'daddy' in desc_lower or '姨姨' in desc_lower or 'aunt' in desc_lower:
                    fixed_item['category'] = 'Family Support'
                elif 'kuok' in desc_lower:
                    fixed_item['category'] = 'Grants/Scholarships'
                elif 'content' in desc_lower:
                    fixed_item['category'] = 'Business Income'
                else:
                    fixed_item['category'] = 'Other Income'
                needs_update = True

            updated_income.append(fixed_item)

        # Fix expense categorization
        for item in pnl['expense_items']:
            fixed_item = item.copy()
            desc_lower = item['description'].lower()

            if item['category'] in ['Expense', 'Other Expenses', 'Other']:
                if 'eat' in desc_lower or 'makan' in desc_lower or 'food' in desc_lower:
                    fixed_item['category'] = 'Food & Dining'
                elif 'shopping' in desc_lower or 'belanja' in desc_lower or 'shopee' in desc_lower:
                    fixed_item['category'] = 'Shopping'
                elif 'transport' in desc_lower:
                    fixed_item['category'] = 'Transportation'
                elif 'laundry' in desc_lower or 'hair cut' in desc_lower:
                    fixed_item['category'] = 'Personal Care'
                elif 'education' in desc_lower or 'self-enrichment' in desc_lower:
                    fixed_item['category'] = 'Education'
                elif 'ai' in desc_lower or 'mac mini' in desc_lower:
                    fixed_item['category'] = 'Technology/Software'
                elif 'entertainment' in desc_lower:
                    fixed_item['category'] = 'Entertainment'
                elif 'exercise' in desc_lower:
                    fixed_item['category'] = 'Fitness & Sports'
                elif 'medicine' in desc_lower or 'health' in desc_lower:
                    fixed_item['category'] = 'Healthcare'
                elif 'espira' in desc_lower:
                    fixed_item['category'] = 'Fees & Charges'
                else:
                    fixed_item['category'] = 'Other Expenses'
                needs_update = True

            updated_expense.append(fixed_item)

        if needs_update:
            print(f"Updating categorization for {period}")
            save_pnl(
                label=pnl['label'],
                income_items=updated_income,
                expense_items=updated_expense,
                period=period
            )

def consolidate_categories():
    """Consolidate similar categories as requested by user."""
    periods = ['2025-08', '2025-09', '2025-10', '2025-11', '2025-12', '2026-01', '2026-02', '2026-03']

    for period in periods:
        pnl = get_pnl_by_period(period)
        if not pnl:
            continue

        updated_expense = []

        for item in pnl['expense_items']:
            # Consolidate similar categories
            category = item['category']

            # Group various shopping/belanja items
            if category in ['Shopping', 'Belanja']:
                category = 'Shopping'

            # Group food-related expenses
            elif category == 'Food & Dining':
                category = 'Food & Dining'

            # Group education-related
            elif category in ['Education', 'Self-Enrichment']:
                category = 'Education'

            # Group personal care
            elif category in ['Personal Care', 'Laundry', 'Hair Cut']:
                category = 'Personal Care'

            # Group technology
            elif category in ['Technology/Software', 'AI', 'Mac Mini']:
                category = 'Technology/Software'

            updated_expense.append({
                **item,
                'category': category
            })

        # Check if any changes were made
        if any(item['category'] != updated_item['category']
               for item, updated_item in zip(pnl['expense_items'], updated_expense)):
            print(f"Consolidating categories for {period}")
            save_pnl(
                label=pnl['label'],
                income_items=pnl['income_items'],
                expense_items=updated_expense,
                period=period
            )

def main():
    print("Cleaning up imported financial data...")

    fix_categorization()
    consolidate_categories()

    print("Data cleanup completed!")

if __name__ == "__main__":
    main()