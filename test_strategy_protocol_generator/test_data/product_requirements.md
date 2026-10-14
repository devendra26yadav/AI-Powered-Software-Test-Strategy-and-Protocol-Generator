# Product Requirements: Inventory Management Web Application

## Overview
The product is a web application for small businesses to manage inventory, suppliers, and stock movements. It must support secure access, accurate stock counts, and a clear audit history.

## Functional Requirements
1. Users must be able to create, view, edit, and archive inventory items.
2. Users must be able to record stock receipts, adjustments, and shipments.
3. The system must warn users when an item falls below its configured reorder threshold.
4. Users must be able to search and filter inventory by name, SKU, supplier, and stock status.
5. The system must retain an audit history for inventory changes.

## Non-Functional Requirements
- Standard inventory pages must load in under 2 seconds for typical account sizes.
- The application must support current versions of major desktop browsers.
- Data must be encrypted in transit and protected by role-based access controls.
- The application must remain usable on tablet-sized screens.

## Business Rules
- Stock quantity must not become negative unless an authorized adjustment explicitly allows it.
- Reorder alerts must use each item's configured threshold.
- Archived items must remain available in historical reports but not appear in active stock lists by default.
