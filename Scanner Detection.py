import os
import re
import ast
from pathlib import Path

# Extensions to scan
VALID_EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.json', '.yaml', '.yml', '.txt', '.prompt'}

# Directories to ignore
IGNORE_DIRS = {'.git', 'node_modules', 'venv', '.venv', '__pycache__', 'dist', 'build', '.next'}

# Patterns to flag
PATTERNS = [
    # 1. Hardcoded 2-item restrictions
    (r'\[:2\]|\.slice\(0,\s*2\)', 'Slicing output or list to 2 items', 'POST-LLM'),
    (r'(limit|max|top_k|max_bullets|num_bullets)\s*[:=]\s*2', 'Explicitly setting a limit or max to 2', 'PRE-LLM / LLM'),
    
    # 2. Prompts restricting count
    (r'(2|two)\s*(bullet|point|briefing|summary|item)', 'Prompt or string specifying 2 bullets/items', 'LLM'),
    (r'(max|up to|exactly|limit to)\s*(2|two)', 'Prompt string capping count to 2', 'LLM'),

    # 3. Retrieval & Note limits
    (r'(limit|top_k|max_notes|num_notes)\s*[:=]\s*\d+', 'Note retrieval limit setting', 'PRE-LLM'),
    (r'SELECT.*LIMIT\s+\d+', 'SQL query limiting retrieved records', 'PRE-LLM'),

    # 4. Post-LLM Grounding / Validation / Filtering
    (r'(grounding|citation|valid|filter|coverage).*bullet', 'Bullet filtering or grounding check', 'POST-LLM'),
    (r'len\(.*(bullet|point|citation|ground).*\)', 'Bullet list length evaluation', 'POST-LLM'),
    (r'\[:(?:max_bullets|limit|count)\]', 'Dynamic slicing of results', 'POST-LLM'),
]

def get_enclosing_function(file_path, line_no):
    """Attempt to identify enclosing python function using AST."""
    if not file_path.endswith('.py'):
        return "N/A"
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=file_path)
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, 'lineno') and hasattr(node, 'end_lineno'):
                    if node.lineno <= line_no <= node.end_lineno:
                        return node.name
    except Exception:
        pass
    return "Unknown/Global"

def scan_project(root_dir='.'):
    findings = []
    
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Exclude ignored directories
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        
        for filename in filenames:
            ext = Path(filename).suffix.lower()
            if ext not in VALID_EXTENSIONS or filename == 'scanner.py':
                continue
            
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root_dir)
            
            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                    
                for idx, line in enumerate(lines, 1):
                    clean_line = line.strip()
                    if not clean_line or clean_line.startswith('#') or clean_line.startswith('//'):
                        continue
                        
                    for pattern, reason, stage in PATTERNS:
                        if re.search(pattern, clean_line, re.IGNORECASE):
                            func_name = get_enclosing_function(full_path, idx)
                            findings.append({
                                'file': rel_path,
                                'line': idx,
                                'function': func_name,
                                'stage': stage,
                                'code': clean_line,
                                'reason': reason
                            })
            except Exception as e:
                pass
                
    return findings

def print_report(findings):
    print("=" * 80)
    print("      GROUNDED APP - BRIEFING BULLET DIAGNOSTIC REPORT")
    print("=" * 80)
    print(f"Total Suspicious Pipeline Nodes Found: {len(findings)}\n")
    
    if not findings:
        print("No obvious hardcoded constraints found via static regex scan.")
        print("Possibility D (Not enough source notes or API response limit) is likely.\n")
        print("ROOT CAUSE: Pending runtime verification")
        print("LLM OR CODE: Unknown")
        print("EXACT FILE + LINE: N/A")
        print("EXPLANATION: Static scan found no hardcoded limiters.")
        print("NEXT TEST: Log raw LLM response before post-processing.")
        return

    stages_found = set()
    for f in findings:
        stages_found.add(f['stage'])
        print(f"FILE: {f['file']}")
        print(f"LINE: {f['line']}")
        print(f"FUNCTION: {f['function']}")
        print(f"STAGE: {f['stage']}")
        print(f"EXACT CODE: {f['code']}")
        print(f"WHY IT COULD CAUSE THE 2-BULLET RESULT: {f['reason']}")
        print("-" * 80)

    print("\n" + "=" * 80)
    print("DIAGNOSTIC SUMMARY & CONCLUSION")
    print("=" * 80)

    # Determine probable stage
    top_finding = findings[0]
    stage_category = "A. Before the LLM" if "PRE-LLM" in top_finding['stage'] else (
                     "B. Inside the LLM prompt/output" if "LLM" in top_finding['stage'] else
                     "C. After the LLM")

    print(f"PROBABLE CATEGORY: {stage_category}")
    print(f"ROOT CAUSE: Found {len(findings)} potential limiting pattern(s) in pipeline.")
    print(f"LLM OR CODE: {'LLM Prompt' if top_finding['stage'] == 'LLM' else 'Backend Code'}")
    print(f"EXACT FILE + LINE: {top_finding['file']}:{top_finding['line']}")
    print(f"EXPLANATION: {top_finding['reason']} in `{top_finding['code']}`.")
    print("NEXT TEST: Inspect the identified file and line to verify if this constraint is active during execution.")

if __name__ == "__main__":
    results = scan_project('.')
    print_report(results)