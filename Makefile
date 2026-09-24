.PHONY: test test-parsers regen-fixtures clean

# Repository-wide entry points. Add corresponding module targets here as
# recipes and downloaders are introduced.
test: test-parsers

test-parsers:
	$(MAKE) -C parsers test

regen-fixtures:
	$(MAKE) -C parsers regen-fixtures

clean:
	$(MAKE) -C parsers clean
