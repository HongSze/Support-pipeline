PYTHON ?= python3

GENERATED = preprocessed_tickets.json classified_tickets.json retrieval_results.json \
            priority_scores.json routing_decisions.json reply_drafts.json \
            retrieval_quality.json ops_summary.md handoff_memory.json \
            validation_report.md llm_calls.jsonl

.PHONY: all run validate clean

all: run validate

run:
	$(PYTHON) run_pipeline.py

validate:
	$(PYTHON) validate.py

clean:
	rm -f $(GENERATED)
