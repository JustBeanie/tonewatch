# ASVS gap register

Each gap names the pinned requirement, the unmet condition, and a target milestone.

## GAP-001 - V1.1.1

- Requirement: Verify that input is decoded or unescaped into a canonical form only once, it is only decoded when encoded data in that form is expected, and that this is done before processing the input further, for example it is not performed after input validation or sanitization.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-002 - V1.1.2

- Requirement: Verify that the application performs output encoding and escaping either as a final step before being used by the interpreter for which it is intended or by the interpreter itself.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-003 - V1.2.1

- Requirement: Verify that output encoding for an HTTP response, HTML document, or XML document is relevant for the context required, such as encoding the relevant characters for HTML elements, HTML attributes, HTML comments, CSS, or HTTP header fields, to avoid changing the message or document structure.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-004 - V1.2.2

- Requirement: Verify that when dynamically building URLs, untrusted data is encoded according to its context (e.g., URL encoding or base64url encoding for query or path parameters). Ensure that only safe URL protocols are permitted (e.g., disallow javascript: or data:).
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-005 - V1.2.3

- Requirement: Verify that output encoding or escaping is used when dynamically building JavaScript content (including JSON), to avoid changing the message or document structure (to avoid JavaScript and JSON injection).
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-006 - V1.2.4

- Requirement: Verify that data selection or database queries (e.g., SQL, HQL, NoSQL, Cypher) use parameterized queries, ORMs, entity frameworks, or are otherwise protected from SQL Injection and other database injection attacks. This is also relevant when writing stored procedures.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-007 - V1.2.5

- Requirement: Verify that the application protects against OS command injection and that operating system calls use parameterized OS queries or use contextual command line output encoding.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-008 - V1.2.6

- Requirement: Verify that the application protects against LDAP injection vulnerabilities, or that specific security controls to prevent LDAP injection have been implemented.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-009 - V1.2.7

- Requirement: Verify that the application is protected against XPath injection attacks by using query parameterization or precompiled queries.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-010 - V1.2.8

- Requirement: Verify that LaTeX processors are configured securely (such as not using the "--shell-escape" flag) and an allowlist of commands is used to prevent LaTeX injection attacks.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-011 - V1.2.9

- Requirement: Verify that the application escapes special characters in regular expressions (typically using a backslash) to prevent them from being misinterpreted as metacharacters.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-012 - V1.3.1

- Requirement: Verify that all untrusted HTML input from WYSIWYG editors or similar is sanitized using a well-known and secure HTML sanitization library or framework feature.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-013 - V1.3.2

- Requirement: Verify that the application avoids the use of eval() or other dynamic code execution features such as Spring Expression Language (SpEL). Where there is no alternative, any user input being included must be sanitized before being executed.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-014 - V1.3.3

- Requirement: Verify that data being passed to a potentially dangerous context is sanitized beforehand to enforce safety measures, such as only allowing characters which are safe for this context and trimming input which is too long.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-015 - V1.3.4

- Requirement: Verify that user-supplied Scalable Vector Graphics (SVG) scriptable content is validated or sanitized to contain only tags and attributes (such as draw graphics) that are safe for the application, e.g., do not contain scripts and foreignObject.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-016 - V1.3.5

- Requirement: Verify that the application sanitizes or disables user-supplied scriptable or expression template language content, such as Markdown, CSS or XSL stylesheets, BBCode, or similar.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-017 - V1.3.7

- Requirement: Verify that the application protects against template injection attacks by not allowing templates to be built based on untrusted input. Where there is no alternative, any untrusted input being included dynamically during template creation must be sanitized or strictly validated.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-018 - V1.3.8

- Requirement: Verify that the application appropriately sanitizes untrusted input before use in Java Naming and Directory Interface (JNDI) queries and that JNDI is configured securely to prevent JNDI injection attacks.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-019 - V1.3.9

- Requirement: Verify that the application sanitizes content before it is sent to memcache to prevent injection attacks.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-020 - V1.3.10

- Requirement: Verify that format strings which might resolve in an unexpected or malicious way when used are sanitized before being processed.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-021 - V1.3.11

- Requirement: Verify that the application sanitizes user input before passing to mail systems to protect against SMTP or IMAP injection.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-022 - V1.4.1

- Requirement: Verify that the application uses memory-safe string, safer memory copy and pointer arithmetic to detect or prevent stack, buffer, or heap overflows.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-023 - V1.4.2

- Requirement: Verify that sign, range, and input validation techniques are used to prevent integer overflows.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-024 - V1.4.3

- Requirement: Verify that dynamically allocated memory and resources are released, and that references or pointers to freed memory are removed or set to null to prevent dangling pointers and use-after-free vulnerabilities.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-025 - V1.5.1

- Requirement: Verify that the application configures XML parsers to use a restrictive configuration and that unsafe features such as resolving external entities are disabled to prevent XML eXternal Entity (XXE) attacks.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-026 - V1.5.2

- Requirement: Verify that deserialization of untrusted data enforces safe input handling, such as using an allowlist of object types or restricting client-defined object types, to prevent deserialization attacks. Deserialization mechanisms that are explicitly defined as insecure must not be used with untrusted input.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-027 - V2.1.2

- Requirement: Verify that the application's documentation defines how to validate the logical and contextual consistency of combined data items, such as checking that suburb and ZIP code match.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-028 - V2.1.3

- Requirement: Verify that expectations for business logic limits and validations are documented, including both per-user and globally across the application.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-029 - V2.2.1

- Requirement: Verify that input is validated to enforce business or functional expectations for that input. This should either use positive validation against an allow list of values, patterns, and ranges, or be based on comparing the input to an expected structure and logical limits according to predefined rules. For L1, this can focus on input which is used to make specific business or security decisions. For L2 and up, this should apply to all input.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-030 - V2.2.2

- Requirement: Verify that the application is designed to enforce input validation at a trusted service layer. While client-side validation improves usability and should be encouraged, it must not be relied upon as a security control.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-031 - V2.2.3

- Requirement: Verify that the application ensures that combinations of related data items are reasonable according to the pre-defined rules.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-032 - V2.3.1

- Requirement: Verify that the application will only process business logic flows for the same user in the expected sequential step order and without skipping steps.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-033 - V2.3.2

- Requirement: Verify that business logic limits are implemented per the application's documentation to avoid business logic flaws being exploited.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-034 - V2.3.3

- Requirement: Verify that transactions are being used at the business logic level such that either a business logic operation succeeds in its entirety or it is rolled back to the previous correct state.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-035 - V2.3.4

- Requirement: Verify that business logic level locking mechanisms are used to ensure that limited quantity resources (such as theater seats or delivery slots) cannot be double-booked by manipulating the application's logic.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-036 - V2.4.1

- Requirement: Verify that anti-automation controls are in place to protect against excessive calls to application functions that could lead to data exfiltration, garbage-data creation, quota exhaustion, rate-limit breaches, denial-of-service, or overuse of costly resources.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-037 - V3.2.2

- Requirement: Verify that content intended to be displayed as text, rather than rendered as HTML, is handled using safe rendering functions (such as createTextNode or textContent) to prevent unintended execution of content such as HTML or JavaScript.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-038 - V3.3.3

- Requirement: Verify that cookies have the '__Host-' prefix for the cookie name unless they are explicitly designed to be shared with other hosts.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-039 - V3.4.5

- Requirement: Verify that the application sets a referrer policy to prevent leakage of technically sensitive data to third-party services via the 'Referer' HTTP request header field. This can be done using the Referrer-Policy HTTP response header field or via HTML element attributes. Sensitive data could include path and query data in the URL, and for internal non-public applications also the hostname.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-040 - V3.5.3

- Requirement: Verify that HTTP requests to sensitive functionality use appropriate HTTP methods such as POST, PUT, PATCH, or DELETE, and not methods defined by the HTTP specification as "safe" such as HEAD, OPTIONS, or GET. Alternatively, strict validation of the Sec-Fetch-* request header fields can be used to ensure that the request did not originate from an inappropriate cross-origin call, a navigation request, or a resource load (such as an image source) where this is not expected.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-041 - V3.5.4

- Requirement: Verify that separate applications are hosted on different hostnames to leverage the restrictions provided by same-origin policy, including how documents or scripts loaded by one origin can interact with resources from another origin and hostname-based restrictions on cookies.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-042 - V3.5.5

- Requirement: Verify that messages received by the postMessage interface are discarded if the origin of the message is not trusted, or if the syntax of the message is invalid.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-043 - V3.7.1

- Requirement: Verify that the application only uses client-side technologies which are still supported and considered secure. Examples of technologies which do not meet this requirement include NSAPI plugins, Flash, Shockwave, ActiveX, Silverlight, NACL, or client-side Java applets.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-044 - V4.1.1

- Requirement: Verify that every HTTP response with a message body contains a Content-Type header field that matches the actual content of the response, including the charset parameter to specify safe character encoding (e.g., UTF-8, ISO-8859-1) according to IANA Media Types, such as "text/", "/+xml" and "/xml".
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-045 - V4.1.3

- Requirement: Verify that any HTTP header field used by the application and set by an intermediary layer, such as a load balancer, a web proxy, or a backend-for-frontend service, cannot be overridden by the end-user. Example headers might include X-Real-IP, X-Forwarded-*, or X-User-ID.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-046 - V4.2.1

- Requirement: Verify that all application components (including load balancers, firewalls, and application servers) determine boundaries of incoming HTTP messages using the appropriate mechanism for the HTTP version to prevent HTTP request smuggling. In HTTP/1.x, if a Transfer-Encoding header field is present, the Content-Length header must be ignored per RFC 2616. When using HTTP/2 or HTTP/3, if a Content-Length header field is present, the receiver must ensure that it is consistent with the length of the DATA frames.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-047 - V4.4.1

- Requirement: Verify that WebSocket over TLS (WSS) is used for all WebSocket connections.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-048 - V4.4.3

- Requirement: Verify that, if the application's standard session management cannot be used, dedicated tokens are being used for this, which comply with the relevant Session Management security requirements.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-049 - V5.2.1

- Requirement: Verify that the application will only accept files of a size which it can process without causing a loss of performance or a denial of service attack.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-050 - V5.2.2

- Requirement: Verify that when the application accepts a file, either on its own or within an archive such as a zip file, it checks if the file extension matches an expected file extension and validates that the contents correspond to the type represented by the extension. This includes, but is not limited to, checking the initial 'magic bytes', performing image re-writing, and using specialized libraries for file content validation. For L1, this can focus just on files which are used to make specific business or security decisions. For L2 and up, this must apply to all files being accepted.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-051 - V5.2.3

- Requirement: Verify that the application checks compressed files (e.g., zip, gz, docx, odt) against maximum allowed uncompressed size and against maximum number of files before uncompressing the file.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-052 - V5.3.1

- Requirement: Verify that files uploaded or generated by untrusted input and stored in a public folder, are not executed as server-side program code when accessed directly with an HTTP request.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-053 - V5.4.1

- Requirement: Verify that the application validates or ignores user-submitted filenames, including in a JSON, JSONP, or URL parameter and specifies a filename in the Content-Disposition header field in the response.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-054 - V5.4.2

- Requirement: Verify that file names served (e.g., in HTTP response header fields or email attachments) are encoded or sanitized (e.g., following RFC 6266) to preserve document structure and prevent injection attacks.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-055 - V5.4.3

- Requirement: Verify that files obtained from untrusted sources are scanned by antivirus scanners to prevent serving of known malicious content.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-056 - V6.1.2

- Requirement: Verify that a list of context-specific words is documented in order to prevent their use in passwords. The list could include permutations of organization names, product names, system identifiers, project codenames, department or role names, and similar.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-057 - V6.1.3

- Requirement: Verify that, if the application includes multiple authentication pathways, these are all documented together with the security controls and authentication strength which must be consistently enforced across them.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-058 - V6.2.1

- Requirement: Verify that user set passwords are at least 8 characters in length although a minimum of 15 characters is strongly recommended.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-059 - V6.2.2

- Requirement: Verify that users can change their password.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-060 - V6.2.3

- Requirement: Verify that password change functionality requires the user's current and new password.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-061 - V6.2.4

- Requirement: Verify that passwords submitted during account registration or password change are checked against an available set of, at least, the top 3000 passwords which match the application's password policy, e.g. minimum length.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-062 - V6.2.5

- Requirement: Verify that passwords of any composition can be used, without rules limiting the type of characters permitted. There must be no requirement for a minimum number of upper or lower case characters, numbers, or special characters.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-063 - V6.2.6

- Requirement: Verify that password input fields use type=password to mask the entry. Applications may allow the user to temporarily view the entire masked password, or the last typed character of the password.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-064 - V6.2.7

- Requirement: Verify that "paste" functionality, browser password helpers, and external password managers are permitted.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-065 - V6.2.8

- Requirement: Verify that the application verifies the user's password exactly as received from the user, without any modifications such as truncation or case transformation.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-066 - V6.2.9

- Requirement: Verify that passwords of at least 64 characters are permitted.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-067 - V6.2.10

- Requirement: Verify that a user's password stays valid until it is discovered to be compromised or the user rotates it. The application must not require periodic credential rotation.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-068 - V6.2.11

- Requirement: Verify that the documented list of context specific words is used to prevent easy to guess passwords being created.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-069 - V6.2.12

- Requirement: Verify that passwords submitted during account registration or password changes are checked against a set of breached passwords.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-070 - V6.3.2

- Requirement: Verify that default user accounts (e.g., "root", "admin", or "sa") are not present in the application or are disabled.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-071 - V6.3.3

- Requirement: Verify that either a multi-factor authentication mechanism or a combination of single-factor authentication mechanisms, must be used in order to access the application. For L3, one of the factors must be a hardware-based authentication mechanism which provides compromise and impersonation resistance against phishing attacks while verifying the intent to authenticate by requiring a user-initiated action (such as a button press on a FIDO hardware key or a mobile phone). Relaxing any of the considerations in this requirement requires a fully documented rationale and a comprehensive set of mitigating controls.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-072 - V6.3.4

- Requirement: Verify that, if the application includes multiple authentication pathways, there are no undocumented pathways and that security controls and authentication strength are enforced consistently.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-073 - V6.4.1

- Requirement: Verify that system generated initial passwords or activation codes are securely randomly generated, follow the existing password policy, and expire after a short period of time or after they are initially used. These initial secrets must not be permitted to become the long term password.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-074 - V6.4.2

- Requirement: Verify that password hints or knowledge-based authentication (so-called "secret questions") are not present.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-075 - V6.4.3

- Requirement: Verify that a secure process for resetting a forgotten password is implemented, that does not bypass any enabled multi-factor authentication mechanisms.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-076 - V6.4.4

- Requirement: Verify that if a multi-factor authentication factor is lost, evidence of identity proofing is performed at the same level as during enrollment.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-077 - V6.5.1

- Requirement: Verify that lookup secrets, out-of-band authentication requests or codes, and time-based one-time passwords (TOTPs) are only successfully usable once.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-078 - V6.5.3

- Requirement: Verify that lookup secrets, out-of-band authentication code, and time-based one-time password seeds, are generated using a Cryptographically Secure Pseudorandom Number Generator (CSPRNG) to avoid predictable values.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-079 - V6.5.4

- Requirement: Verify that lookup secrets and out-of-band authentication codes have a minimum of 20 bits of entropy (typically 4 random alphanumeric characters or 6 random digits is sufficient).
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-080 - V6.6.1

- Requirement: Verify that authentication mechanisms using the Public Switched Telephone Network (PSTN) to deliver One-time Passwords (OTPs) via phone or SMS are offered only when the phone number has previously been validated, alternate stronger methods (such as Time based One-time Passwords) are also offered, and the service provides information on their security risks to users. For L3 applications, phone and SMS must not be available as options.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-081 - V6.6.2

- Requirement: Verify that out-of-band authentication requests, codes, or tokens are bound to the original authentication request for which they were generated and are not usable for a previous or subsequent one.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-082 - V6.8.1

- Requirement: Verify that, if the application supports multiple identity providers (IdPs), the user's identity cannot be spoofed via another supported identity provider (eg. by using the same user identifier). The standard mitigation would be for the application to register and identify the user using a combination of the IdP ID (serving as a namespace) and the user's ID in the IdP.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-083 - V7.1.1

- Requirement: Verify that the user's session inactivity timeout and absolute maximum session lifetime are documented, are appropriate in combination with other controls, and that the documentation includes justification for any deviations from NIST SP 800-63B re-authentication requirements.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-084 - V7.1.2

- Requirement: Verify that the documentation defines how many concurrent (parallel) sessions are allowed for one account as well as the intended behaviors and actions to be taken when the maximum number of active sessions is reached.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-085 - V7.2.1

- Requirement: Verify that the application performs all session token verification using a trusted, backend service.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-086 - V7.2.2

- Requirement: Verify that the application uses either self-contained or reference tokens that are dynamically generated for session management, i.e. not using static API secrets and keys.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-087 - V7.2.3

- Requirement: Verify that if reference tokens are used to represent user sessions, they are unique and generated using a cryptographically secure pseudo-random number generator (CSPRNG) and possess at least 128 bits of entropy.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-088 - V7.2.4

- Requirement: Verify that the application generates a new session token on user authentication, including re-authentication, and terminates the current session token.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-089 - V7.3.1

- Requirement: Verify that there is an inactivity timeout such that re-authentication is enforced according to risk analysis and documented security decisions.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-090 - V7.3.2

- Requirement: Verify that there is an absolute maximum session lifetime such that re-authentication is enforced according to risk analysis and documented security decisions.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-091 - V7.4.2

- Requirement: Verify that the application terminates all active sessions when a user account is disabled or deleted (such as an employee leaving the company).
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-092 - V7.4.3

- Requirement: Verify that the application gives the option to terminate all other active sessions after a successful change or removal of any authentication factor (including password change via reset or recovery and, if present, an MFA settings update).
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-093 - V7.4.4

- Requirement: Verify that all pages that require authentication have easy and visible access to logout functionality.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-094 - V7.4.5

- Requirement: Verify that application administrators are able to terminate active sessions for an individual user or for all users.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-095 - V7.5.1

- Requirement: Verify that the application requires full re-authentication before allowing modifications to sensitive account attributes which may affect authentication such as email address, phone number, MFA configuration, or other information used in account recovery.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-096 - V7.5.2

- Requirement: Verify that users are able to view and (having authenticated again with at least one factor) terminate any or all currently active sessions.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-097 - V7.6.1

- Requirement: Verify that session lifetime and termination between Relying Parties (RPs) and Identity Providers (IdPs) behave as documented, requiring re-authentication as necessary such as when the maximum time between IdP authentication events is reached.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-098 - V7.6.2

- Requirement: Verify that creation of a session requires either the user's consent or an explicit action, preventing the creation of new application sessions without user interaction.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-099 - V8.1.1

- Requirement: Verify that authorization documentation defines rules for restricting function-level and data-specific access based on consumer permissions and resource attributes.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-100 - V8.1.2

- Requirement: Verify that authorization documentation defines rules for field-level access restrictions (both read and write) based on consumer permissions and resource attributes. Note that these rules might depend on other attribute values of the relevant data object, such as state or status.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-101 - V8.2.1

- Requirement: Verify that the application ensures that function-level access is restricted to consumers with explicit permissions.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-102 - V8.2.2

- Requirement: Verify that the application ensures that data-specific access is restricted to consumers with explicit permissions to specific data items to mitigate insecure direct object reference (IDOR) and broken object level authorization (BOLA).
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-103 - V8.2.3

- Requirement: Verify that the application ensures that field-level access is restricted to consumers with explicit permissions to specific fields to mitigate broken object property level authorization (BOPLA).
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-104 - V8.3.1

- Requirement: Verify that the application enforces authorization rules at a trusted service layer and doesn't rely on controls that an untrusted consumer could manipulate, such as client-side JavaScript.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9

## GAP-105 - V8.4.1

- Requirement: Verify that multi-tenant applications use cross-tenant controls to ensure consumer operations will never affect tenants with which they do not have permissions to interact.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: M9



















## GAP-124 - V11.1.1

- Requirement: Verify that there is a documented policy for management of cryptographic keys and a cryptographic key lifecycle that follows a key management standard such as NIST SP 800-57. This should include ensuring that keys are not overshared (for example, with more than two entities for shared secrets and more than one entity for private keys).
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-125 - V11.1.2

- Requirement: Verify that a cryptographic inventory is performed, maintained, regularly updated, and includes all cryptographic keys, algorithms, and certificates used by the application. It must also document where keys can and cannot be used in the system, and the types of data that can and cannot be protected using the keys.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-126 - V11.2.1

- Requirement: Verify that industry-validated implementations (including libraries and hardware-accelerated implementations) are used for cryptographic operations.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-127 - V11.2.2

- Requirement: Verify that the application is designed with crypto agility such that random number, authenticated encryption, MAC, or hashing algorithms, key lengths, rounds, ciphers and modes can be reconfigured, upgraded, or swapped at any time, to protect against cryptographic breaks. Similarly, it must also be possible to replace keys and passwords and re-encrypt data. This will allow for seamless upgrades to post-quantum cryptography (PQC), once high-assurance implementations of approved PQC schemes or standards are widely available.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-128 - V11.2.3

- Requirement: Verify that all cryptographic primitives utilize a minimum of 128-bits of security based on the algorithm, key size, and configuration. For example, a 256-bit ECC key provides roughly 128 bits of security where RSA requires a 3072-bit key to achieve 128 bits of security.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-129 - V11.3.1

- Requirement: Verify that insecure block modes (e.g., ECB) and weak padding schemes (e.g., PKCS#1 v1.5) are not used.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-130 - V11.3.2

- Requirement: Verify that only approved ciphers and modes such as AES with GCM are used.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-131 - V11.3.3

- Requirement: Verify that encrypted data is protected against unauthorized modification preferably by using an approved authenticated encryption method or by combining an approved encryption method with an approved MAC algorithm.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-132 - V11.4.1

- Requirement: Verify that only approved hash functions are used for general cryptographic use cases, including digital signatures, HMAC, KDF, and random bit generation. Disallowed hash functions, such as MD5, must not be used for any cryptographic purpose.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-133 - V11.4.3

- Requirement: Verify that hash functions used in digital signatures, as part of data authentication or data integrity are collision resistant and have appropriate bit-lengths. If collision resistance is required, the output length must be at least 256 bits. If only resistance to second pre-image attacks is required, the output length must be at least 128 bits.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-134 - V11.4.4

- Requirement: Verify that the application uses approved key derivation functions with key stretching parameters when deriving secret keys from passwords. The parameters in use must balance security and performance to prevent brute-force attacks from compromising the resulting cryptographic key.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-135 - V11.5.1

- Requirement: Verify that all random numbers and strings which are intended to be non-guessable must be generated using a cryptographically secure pseudo-random number generator (CSPRNG) and have at least 128 bits of entropy. Note that UUIDs do not respect this condition.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-136 - V11.6.1

- Requirement: Verify that only approved cryptographic algorithms and modes of operation are used for key generation and seeding, and digital signature generation and verification. Key generation algorithms must not generate insecure keys vulnerable to known attacks, for example, RSA keys which are vulnerable to Fermat factorization.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-137 - V12.1.1

- Requirement: Verify that only the latest recommended versions of the TLS protocol are enabled, such as TLS 1.2 and TLS 1.3. The latest version of the TLS protocol must be the preferred option.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-138 - V12.1.2

- Requirement: Verify that only recommended cipher suites are enabled, with the strongest cipher suites set as preferred. L3 applications must only support cipher suites which provide forward secrecy.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-139 - V12.2.1

- Requirement: Verify that TLS is used for all connectivity between a client and external facing, HTTP-based services, and does not fall back to insecure or unencrypted communications.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-140 - V12.2.2

- Requirement: Verify that external facing services use publicly trusted TLS certificates.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-141 - V12.3.1

- Requirement: Verify that an encrypted protocol such as TLS is used for all inbound and outbound connections to and from the application, including monitoring systems, management tools, remote access and SSH, middleware, databases, mainframes, partner systems, or external APIs. The server must not fall back to insecure or unencrypted protocols.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-142 - V12.3.3

- Requirement: Verify that TLS or another appropriate transport encryption mechanism used for all connectivity between internal, HTTP-based services within the application, and does not fall back to insecure or unencrypted communications.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-143 - V13.1.1

- Requirement: Verify that all communication needs for the application are documented. This must include external services which the application relies upon and cases where an end user might be able to provide an external location to which the application will then connect.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-144 - V13.2.1

- Requirement: Verify that communications between backend application components that don't support the application's standard user session mechanism, including APIs, middleware, and data layers, are authenticated. Authentication must use individual service accounts, short-term tokens, or certificate-based authentication and not unchanging credentials such as passwords, API keys, or shared accounts with privileged access.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-145 - V13.2.2

- Requirement: Verify that communications between backend application components, including local or operating system services, APIs, middleware, and data layers, are performed with accounts assigned the least necessary privileges.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-146 - V13.2.3

- Requirement: Verify that if a credential has to be used for service authentication, the credential being used by the consumer is not a default credential (e.g., root/root or admin/admin).
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-147 - V13.2.4

- Requirement: Verify that an allowlist is used to define the external resources or systems with which the application is permitted to communicate (e.g., for outbound requests, data loads, or file access). This allowlist can be implemented at the application layer, web server, firewall, or a combination of different layers.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-148 - V13.2.5

- Requirement: Verify that the web or application server is configured with an allowlist of resources or systems to which the server can send requests or load data or files from.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-149 - V13.3.1

- Requirement: Verify that a secrets management solution, such as a key vault, is used to securely create, store, control access to, and destroy backend secrets. These could include passwords, key material, integrations with databases and third-party systems, keys and seeds for time-based tokens, other internal secrets, and API keys. Secrets must not be included in application source code or included in build artifacts. For an L3 application, this must involve a hardware-backed solution such as an HSM.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-150 - V13.3.2

- Requirement: Verify that access to secret assets adheres to the principle of least privilege.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-151 - V13.4.1

- Requirement: Verify that the application is deployed either without any source control metadata, including the .git or .svn folders, or in a way that these folders are inaccessible both externally and to the application itself.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-152 - V13.4.2

- Requirement: Verify that debug modes are disabled for all components in production environments to prevent exposure of debugging features and information leakage.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-153 - V13.4.3

- Requirement: Verify that web servers do not expose directory listings to clients unless explicitly intended.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-154 - V13.4.4

- Requirement: Verify that using the HTTP TRACE method is not supported in production environments, to avoid potential information leakage.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-155 - V13.4.5

- Requirement: Verify that documentation (such as for internal APIs) and monitoring endpoints are not exposed unless explicitly intended.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-156 - V14.1.1

- Requirement: Verify that all sensitive data created and processed by the application has been identified and classified into protection levels. This includes data that is only encoded and therefore easily decoded, such as Base64 strings or the plaintext payload inside a JWT. Protection levels need to take into account any data protection and privacy regulations and standards which the application is required to comply with.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-157 - V14.1.2

- Requirement: Verify that all sensitive data protection levels have a documented set of protection requirements. This must include (but not be limited to) requirements related to general encryption, integrity verification, retention, how the data is to be logged, access controls around sensitive data in logs, database-level encryption, privacy and privacy-enhancing technologies to be used, and other confidentiality requirements.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-158 - V14.2.1

- Requirement: Verify that sensitive data is only sent to the server in the HTTP message body or header fields, and that the URL and query string do not contain sensitive information, such as an API key or session token.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-159 - V14.2.2

- Requirement: Verify that the application prevents sensitive data from being cached in server components, such as load balancers and application caches, or ensures that the data is securely purged after use.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-160 - V14.2.3

- Requirement: Verify that defined sensitive data is not sent to untrusted parties (e.g., user trackers) to prevent unwanted collection of data outside of the application's control.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-161 - V14.2.4

- Requirement: Verify that controls around sensitive data related to encryption, integrity verification, retention, how the data is to be logged, access controls around sensitive data in logs, privacy and privacy-enhancing technologies, are implemented as defined in the documentation for the specific data's protection level.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-162 - V14.3.1

- Requirement: Verify that authenticated data is cleared from client storage, such as the browser DOM, after the client or session is terminated. The 'Clear-Site-Data' HTTP response header field may be able to help with this but the client-side should also be able to clear up if the server connection is not available when the session is terminated.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-163 - V14.3.2

- Requirement: Verify that the application sets sufficient anti-caching HTTP response header fields (i.e., Cache-Control: no-store) so that sensitive data is not cached in browsers.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-164 - V14.3.3

- Requirement: Verify that data stored in browser storage (such as localStorage, sessionStorage, IndexedDB, or cookies) does not contain sensitive data, with the exception of session tokens.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-165 - V15.1.1

- Requirement: Verify that application documentation defines risk based remediation time frames for 3rd party component versions with vulnerabilities and for updating libraries in general, to minimize the risk from these components.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-166 - V15.1.2

- Requirement: Verify that an inventory catalog, such as software bill of materials (SBOM), is maintained of all third-party libraries in use, including verifying that components come from pre-defined, trusted, and continually maintained repositories.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-167 - V15.1.3

- Requirement: Verify that the application documentation identifies functionality which is time-consuming or resource-demanding. This must include how to prevent a loss of availability due to overusing this functionality and how to avoid a situation where building a response takes longer than the consumer's timeout. Potential defenses may include asynchronous processing, using queues, and limiting parallel processes per user and per application.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-168 - V15.2.1

- Requirement: Verify that the application only contains components which have not breached the documented update and remediation time frames.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-169 - V15.2.2

- Requirement: Verify that the application has implemented defenses against loss of availability due to functionality which is time-consuming or resource-demanding, based on the documented security decisions and strategies for this.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-170 - V15.2.3

- Requirement: Verify that the production environment only includes functionality that is required for the application to function, and does not expose extraneous functionality such as test code, sample snippets, and development functionality.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-171 - V15.3.1

- Requirement: Verify that the application only returns the required subset of fields from a data object. For example, it should not return an entire data object, as some individual fields should not be accessible to users.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-172 - V15.3.3

- Requirement: Verify that the application has countermeasures to protect against mass assignment attacks by limiting allowed fields per controller and action, e.g., it is not possible to insert or update a field value when it was not intended to be part of that action.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-173 - V15.3.5

- Requirement: Verify that the application explicitly ensures that variables are of the correct type and performs strict equality and comparator operations. This is to avoid type juggling or type confusion vulnerabilities caused by the application code making an assumption about a variable type.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-174 - V15.3.6

- Requirement: Verify that JavaScript code is written in a way that prevents prototype pollution, for example, by using Set() or Map() instead of object literals.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-175 - V15.3.7

- Requirement: Verify that the application has defenses against HTTP parameter pollution attacks, particularly if the application framework makes no distinction about the source of request parameters (query string, body parameters, cookies, or header fields).
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-176 - V16.1.1

- Requirement: Verify that an inventory exists documenting the logging performed at each layer of the application's technology stack, what events are being logged, log formats, where that logging is stored, how it is used, how access to it is controlled, and for how long logs are kept.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-177 - V16.2.1

- Requirement: Verify that each log entry includes necessary metadata (such as when, where, who, what) that would allow for a detailed investigation of the timeline when an event happens.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-178 - V16.2.3

- Requirement: Verify that the application only stores or broadcasts logs to the files and services that are documented in the log inventory.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-179 - V16.2.4

- Requirement: Verify that logs can be read and correlated by the log processor that is in use, preferably by using a common logging format.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-180 - V16.3.1

- Requirement: Verify that all authentication operations are logged, including successful and unsuccessful attempts. Additional metadata, such as the type of authentication or factors used, should also be collected.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-181 - V16.3.4

- Requirement: Verify that the application logs unexpected errors and security control failures such as backend TLS failures.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-182 - V16.4.1

- Requirement: Verify that all logging components appropriately encode data to prevent log injection.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-183 - V16.4.2

- Requirement: Verify that logs are protected from unauthorized access and cannot be modified.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-184 - V16.4.3

- Requirement: Verify that logs are securely transmitted to a logically separate system for analysis, detection, alerting, and escalation. The aim is to ensure that if the application is breached, the logs are not compromised.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5

## GAP-185 - V16.5.2

- Requirement: Verify that the application continues to operate securely when external resource access fails, for example, by using patterns such as circuit breakers or graceful degradation.
- Why unmet: No verified ToneWatch control and regression test currently satisfies this requirement.
- Target milestone: S5






## GAP-191 - V3.2.1

- Requirement: Verify that security controls prevent browsers rendering APIs or uploads in an incorrect context.
- Why unmet: ToneWatch does not yet enforce a browser-context, CSP sandbox, or attachment control for every direct resource response.
- Target milestone: S5

## GAP-192 - V3.4.3

- Requirement: Verify that the Content-Security-Policy explicitly includes object-src 'none' and base-uri 'none'.
- Why unmet: The existing global CSP is restrictive but does not declare those two ASVS-required directives explicitly.
- Target milestone: S5

## GAP-193 - V1.3.6

- Requirement: V1.3.6 requires a fully verified SSRF defense for application-initiated requests.
- Why unmet: No single reviewed evidence and regression pair proves the complete ASVS control.
- Target milestone: S5

## GAP-194 - V5.1.1

- Requirement: V5.1.1 requires complete file-upload handling controls.
- Why unmet: The reviewed upload-limit test does not prove every applicable file-handling safeguard.
- Target milestone: S5

## GAP-195 - V6.1.1

- Requirement: V6.1.1 requires the stated authentication control.
- Why unmet: Login throttling is not direct evidence for this requirement.
- Target milestone: S5

## GAP-196 - V6.3.1

- Requirement: V6.3.1 requires the stated password control.
- Why unmet: The cited throttle test does not directly enforce that password requirement.
- Target milestone: S5

## GAP-197 - V6.6.3

- Requirement: V6.6.3 requires the stated credential-recovery control.
- Why unmet: Bounded throttle state is not direct evidence for the full recovery control.
- Target milestone: S5

## GAP-198 - V16.2.2

- Requirement: V16.2.2 requires synchronized time sources for security logging.
- Why unmet: ToneWatch does not configure or verify time synchronization.
- Target milestone: M12

## GAP-199 - V16.3.2

- Requirement: V16.3.2 requires logging of failed authorization attempts.
- Why unmet: Redacted request logging does not directly prove failed authorization event logging.
- Target milestone: S5

## GAP-200 - V16.3.3

- Requirement: V16.3.3 requires the defined security-event logging coverage.
- Why unmet: The reviewed audit test does not establish every documented security event.
- Target milestone: S5

## GAP-201 - V3.3.1

- Requirement: V3.3.1 requires secure session cookies.
- Why unmet: Secure-cookie behavior is conditional on HTTPS and is not verified as universal.
- Target milestone: M12

## GAP-202 - V3.5.1

- Requirement: V3.5.1 requires the applicable anti-forgery control.
- Why unmet: The CORS test does not directly assert that control.
- Target milestone: S5

## GAP-203 - V6.5.2

- Requirement: V6.5.2 requires the stated lookup-secret entropy handling.
- Why unmet: Password hashing evidence does not establish the lookup-secret condition.
- Target milestone: S5

## GAP-204 - V16.5.3

- Requirement: V16.5.3 requires secure fail-closed exception handling.
- Why unmet: The safe-error test does not directly prove all validation failures fail closed.
- Target milestone: S5
